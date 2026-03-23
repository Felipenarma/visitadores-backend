from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
import io
import re
from ..database import get_db
from ..models import Doctor, MedicalRep, BusinessLine, CardexUpload

router = APIRouter(prefix="/api/cardex", tags=["cardex"])

# Smart column mapping: maps many possible names to our internal names
COLUMN_PATTERNS = {
    "nombre_medico": [
        r"^nombre.*medico", r"^nombre.*doctor", r"^doctor$", r"^medico$", r"^nombre.*dr",
        r"^physician", r"^name.*doctor", r"^nombre.*completo", r"^nombre$",
        r"^medico.*nombre", r"^doctor.*nombre", r"^profesional$", r"^médico",
    ],
    "especialidad": [
        r"especialidad", r"specialty", r"especializaci", r"area.*medica",
        r"rama", r"disciplina", r"sub.*especialidad",
    ],
    "direccion": [
        r"direcci", r"domicilio", r"address", r"ubicaci", r"consultorio",
        r"calle", r"ciudad", r"comuna", r"regi[oó]n",
    ],
    "telefono": [
        r"tel[eé]fono", r"phone", r"celular", r"m[oó]vil", r"contacto.*tel",
        r"fono", r"whatsapp", r"wsp", r"^tel$",
    ],
    "email": [
        r"e-?mail", r"correo", r"mail",
    ],
    "nombre_visitador": [
        r"visitador", r"representante", r"^rep$", r"vendedor", r"asesor",
        r"ejecutivo", r"nombre.*rep", r"nombre.*visit", r"asignado",
        r"promotor", r"agente", r"responsable",
    ],
    "linea_negocio": [
        r"l[ií]nea", r"business.*line", r"categor[ií]a", r"divisi[oó]n",
        r"unidad.*negocio", r"segmento", r"^area$",
    ],
    "frecuencia_visita_dias": [
        r"frecuencia", r"frequency", r"periodicidad", r"cada.*d[ií]as",
        r"intervalo", r"ciclo",
    ],
    "productos_prescribe": [
        r"producto", r"prescri", r"medicamento", r"f[aá]rmaco",
        r"receta", r"tratamiento", r"product",
    ],
    "notas": [
        r"^nota", r"observaci", r"comentario", r"^notes$", r"^obs$",
        r"detalle", r"informaci[oó]n.*adicional", r"remarks", r"prioridad",
        r"estado", r"status", r"clasificaci",
    ],
}


def smart_map_columns(df_columns: list) -> dict:
    """Map arbitrary column names to our expected columns using pattern matching."""
    mapping = {}
    used_cols = set()

    # Normalize column names for matching
    normalized = {}
    for col in df_columns:
        norm = str(col).lower().strip().replace(" ", "_").replace(".", "")
        normalized[col] = norm

    # First pass: try to match each of our fields
    for field, patterns in COLUMN_PATTERNS.items():
        best_match = None
        for col, norm in normalized.items():
            if col in used_cols:
                continue
            for pattern in patterns:
                if re.search(pattern, norm):
                    best_match = col
                    break
            if best_match:
                break
        if best_match:
            mapping[best_match] = field
            used_cols.add(best_match)

    return mapping


def find_doctor_name_column(df: pd.DataFrame, already_mapped: dict) -> str:
    """Find the best column for doctor names using heuristics."""
    mapped_cols = set(already_mapped.keys())

    candidates = []
    for col in df.columns:
        if col in mapped_cols:
            continue
        col_lower = str(col).lower().strip()
        # Skip obvious non-name columns
        if col_lower in ('n°', 'nro', '#', 'id', 'num', 'numero', 'número'):
            continue

        series = df[col].dropna()
        if len(series) == 0:
            continue

        # Check if column has string data that looks like names
        str_vals = series.astype(str).tolist()
        # Count values that look like names (have letters, reasonable length)
        name_like = 0
        for v in str_vals[:30]:  # Check first 30 rows
            v = v.strip()
            if len(v) < 3:
                continue
            if v.replace('.', '').replace(',', '').strip().isdigit():
                continue
            if any(c.isalpha() for c in v):
                # Looks like it could be a name
                name_like += 1

        if name_like > 0:
            # Score: higher is better
            score = name_like / max(len(str_vals[:30]), 1)
            # Bonus for columns with "Dr" or name-like patterns
            has_dr = sum(1 for v in str_vals[:30] if 'dr' in v.lower() or 'dra' in v.lower())
            if has_dr > 0:
                score += 2.0
            # Bonus for column name hinting at names
            if any(kw in col_lower for kw in ['nombre', 'doctor', 'medico', 'médico', 'profesional', 'dr']):
                score += 3.0
            candidates.append((col, score))

    if candidates:
        candidates.sort(key=lambda x: -x[1])
        return candidates[0][0]
    return None


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Remove junk rows: summary rows, empty rows, header repeats."""
    if df.empty:
        return df

    rows_to_drop = []
    for idx, row in df.iterrows():
        vals = [str(v).strip().lower() for v in row.values if pd.notna(v)]
        joined = ' '.join(vals)

        # Skip summary/total rows
        if any(kw in joined for kw in ['total:', 'total ', 'prospectos', 'resumen', 'subtotal']):
            rows_to_drop.append(idx)
            continue

        # Skip rows that are mostly empty
        non_empty = [v for v in row.values if pd.notna(v) and str(v).strip() != '']
        if len(non_empty) <= 1:
            rows_to_drop.append(idx)
            continue

        # Skip rows that look like repeated headers
        if any(kw in joined for kw in ['n°', 'nombre', 'especialidad', 'telefono', 'teléfono']):
            str_count = sum(1 for v in row.values if pd.notna(v) and isinstance(v, str) and not v.strip().replace('.','').isdigit())
            if str_count >= 3:  # Multiple header-like strings
                rows_to_drop.append(idx)
                continue

    if rows_to_drop:
        df = df.drop(rows_to_drop)

    return df.reset_index(drop=True)


def try_read_file(content: bytes, filename: str) -> pd.DataFrame:
    """Try to read a file, handling multiple formats and structures."""
    fname = filename.lower()

    if fname.endswith('.csv'):
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            for sep in [',', ';', '\t', '|']:
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=encoding, sep=sep)
                    if len(df.columns) > 1:
                        return df
                except:
                    continue
        return pd.read_csv(io.BytesIO(content), encoding='latin-1')

    if fname.endswith(('.xlsx', '.xls')):
        try:
            xls = pd.ExcelFile(io.BytesIO(content))
            best_df = None
            best_cols = 0

            for sheet in xls.sheet_names:
                # Try reading with different header rows
                for header_row in [0, 1, 2, 3]:
                    try:
                        df = pd.read_excel(xls, sheet_name=sheet, header=header_row)
                        if df.empty:
                            continue
                        # Score this interpretation
                        str_cols = sum(1 for c in df.columns if isinstance(c, str) and len(str(c)) > 2 and not str(c).startswith('Unnamed'))
                        data_rows = len(df.dropna(how='all'))
                        score = str_cols * data_rows
                        if score > best_cols:
                            best_cols = score
                            best_df = df
                    except:
                        continue

            if best_df is not None:
                return best_df

            # Fallback
            return pd.read_excel(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error leyendo Excel: {str(e)}")

    if fname.endswith('.txt'):
        for sep in ['\t', ',', ';', '|']:
            try:
                df = pd.read_csv(io.BytesIO(content), sep=sep, encoding='utf-8')
                if len(df.columns) > 1:
                    return df
            except:
                continue
        return pd.read_csv(io.BytesIO(content), sep='\t', encoding='latin-1')

    raise HTTPException(status_code=400, detail="Formato no soportado. Use CSV, Excel (.xlsx/.xls) o TXT.")


@router.get("/template")
def download_template():
    example = {
        "nombre_medico": "Dr. Juan Pérez",
        "especialidad": "Dermatología",
        "direccion": "Av. Principal 123, CDMX",
        "telefono": "555-1234567",
        "email": "juan.perez@hospital.com",
        "nombre_visitador": "María González",
        "linea_negocio": "Dermatología",
        "frecuencia_visita_dias": 30,
        "productos_prescribe": "Producto A, Producto B",
        "notas": "Prefiere visitas por la mañana"
    }
    df = pd.DataFrame([example])
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plantilla_cardex.xlsx"}
    )


@router.post("/upload")
async def upload_cardex(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No se proporcionó archivo")

    content = await file.read()

    try:
        df = try_read_file(content, file.filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer archivo: {str(e)}")

    if df.empty:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    # Clean junk rows
    df = clean_dataframe(df)

    if df.empty:
        raise HTTPException(status_code=400, detail="No se encontraron datos válidos después de limpiar el archivo")

    # Smart column mapping
    col_mapping = smart_map_columns(list(df.columns))

    # Rename mapped columns
    if col_mapping:
        df = df.rename(columns=col_mapping)

    # If we still don't have nombre_medico, find it with heuristics
    if "nombre_medico" not in df.columns:
        name_col = find_doctor_name_column(df, col_mapping)
        if name_col:
            df = df.rename(columns={name_col: "nombre_medico"})

    # Last resort: normalize remaining unmapped columns
    rename_map = {}
    for col in df.columns:
        if col not in (list(col_mapping.values()) + ["nombre_medico"]):
            norm = str(col).lower().strip().replace(" ", "_")
            rename_map[col] = norm
    if rename_map:
        df = df.rename(columns=rename_map)

    if "nombre_medico" not in df.columns:
        found_cols = [str(c) for c in df.columns][:15]
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo identificar la columna de nombres de médicos. Columnas encontradas: {', '.join(found_cols)}. Asegúrate de que al menos una columna contenga nombres de médicos (ej: 'Nombre', 'Doctor', 'Médico')."
        )

    upload = CardexUpload(filename=file.filename, rows_processed=0)
    db.add(upload)
    db.flush()

    created = 0
    updated = 0
    errors = []
    rep_cache = {}
    bl_cache = {}

    for idx, row in df.iterrows():
        try:
            name = _safe_str(row, "nombre_medico")
            if not name:
                continue
            # Skip entries that are just numbers
            if name.replace('.', '').replace(',', '').strip().isdigit():
                continue
            # Skip very short entries
            if len(name) < 3:
                continue

            specialty = _safe_str(row, "especialidad")
            address = _safe_str(row, "direccion")
            phone = _safe_str(row, "telefono")
            email = _safe_str(row, "email")
            rep_name = _safe_str(row, "nombre_visitador")
            bl_name = _safe_str(row, "linea_negocio")
            prescribes = _safe_str(row, "productos_prescribe")
            notes = _safe_str(row, "notas")

            freq_raw = row.get("frecuencia_visita_dias", 30)
            try:
                frequency = int(float(str(freq_raw))) if freq_raw and str(freq_raw).lower() not in ("nan", "none", "") else 30
            except (ValueError, TypeError):
                frequency = 30

            # Find or create rep
            rep_id = None
            if rep_name:
                if rep_name not in rep_cache:
                    rep = db.query(MedicalRep).filter(MedicalRep.name.ilike(f"%{rep_name}%")).first()
                    if not rep:
                        email_gen = rep_name.lower().replace(' ', '.').replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
                        rep = MedicalRep(name=rep_name, email=f"{email_gen}@company.com")
                        db.add(rep)
                        db.flush()
                    rep_cache[rep_name] = rep.id
                rep_id = rep_cache[rep_name]

            # Find or create business line
            bl_id = None
            if bl_name:
                if bl_name not in bl_cache:
                    bl = db.query(BusinessLine).filter(BusinessLine.name.ilike(f"%{bl_name}%")).first()
                    if not bl:
                        bl = BusinessLine(name=bl_name)
                        db.add(bl)
                        db.flush()
                    bl_cache[bl_name] = bl.id
                bl_id = bl_cache[bl_name]

            # Find or create doctor
            existing = db.query(Doctor).filter(Doctor.name.ilike(name)).first()
            if existing:
                if specialty: existing.specialty = specialty
                if address: existing.address = address
                if phone: existing.phone = phone
                if email: existing.email = email
                if rep_id: existing.rep_id = rep_id
                if bl_id: existing.business_line_id = bl_id
                existing.visit_frequency = frequency
                if prescribes: existing.prescribes_products = prescribes
                if notes: existing.notes = notes
                existing.is_active = True
                updated += 1
            else:
                doctor = Doctor(
                    name=name,
                    specialty=specialty,
                    address=address,
                    phone=phone,
                    email=email,
                    rep_id=rep_id,
                    business_line_id=bl_id,
                    visit_frequency=frequency,
                    prescribes_products=prescribes,
                    notes=notes,
                )
                db.add(doctor)
                created += 1

        except Exception as e:
            errors.append(f"Fila {idx + 2}: {str(e)}")

    upload.rows_processed = created + updated
    db.commit()

    # Build column detection info
    detected = []
    for orig, mapped in col_mapping.items():
        detected.append(f"{orig} → {mapped}")

    return {
        "message": f"Cardex cargado exitosamente",
        "upload_id": upload.id,
        "total_rows": len(df),
        "created": created,
        "updated": updated,
        "columns_detected": detected if detected else [str(c) for c in df.columns],
        "errors": errors[:10],
    }


def _safe_str(row, field):
    """Safely extract a string value from a row."""
    val = row.get(field, None)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", ""):
        return None
    return s
