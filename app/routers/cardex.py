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
        r"nombre.*medico", r"nombre.*doctor", r"doctor", r"medico", r"nombre.*dr",
        r"physician", r"name.*doctor", r"dr\.?", r"nombre.*completo", r"nombre",
        r"medico.*nombre", r"doctor.*nombre", r"profesional",
    ],
    "especialidad": [
        r"especialidad", r"specialty", r"especialización", r"especializacion",
        r"area.*medica", r"rama", r"disciplina",
    ],
    "direccion": [
        r"direcci[oó]n", r"domicilio", r"address", r"ubicaci[oó]n",
        r"consultorio", r"calle", r"direcc",
    ],
    "telefono": [
        r"tel[eé]fono", r"phone", r"celular", r"m[oó]vil", r"contacto.*tel",
        r"n[uú]mero", r"tel\.?", r"fono",
    ],
    "email": [
        r"e-?mail", r"correo", r"correo.*electr[oó]nico", r"mail",
    ],
    "nombre_visitador": [
        r"visitador", r"representante", r"rep", r"vendedor", r"asesor",
        r"ejecutivo", r"nombre.*rep", r"nombre.*visit", r"asignado",
        r"promotor", r"agente",
    ],
    "linea_negocio": [
        r"l[ií]nea", r"business.*line", r"categor[ií]a", r"divisi[oó]n",
        r"unidad.*negocio", r"producto.*l[ií]nea", r"segmento", r"area",
    ],
    "frecuencia_visita_dias": [
        r"frecuencia", r"frequency", r"d[ií]as", r"periodicidad",
        r"cada.*d[ií]as", r"intervalo", r"ciclo",
    ],
    "productos_prescribe": [
        r"producto", r"prescri", r"medicamento", r"f[aá]rmaco",
        r"droga", r"receta", r"tratamiento", r"product",
    ],
    "notas": [
        r"nota", r"observaci[oó]n", r"comentario", r"notes", r"obs",
        r"detalle", r"informaci[oó]n.*adicional", r"remarks",
    ],
}


def smart_map_columns(df_columns: list) -> dict:
    """Map arbitrary column names to our expected columns using pattern matching."""
    mapping = {}
    used_cols = set()
    normalized = {col: col.lower().strip().replace(" ", "_").replace(".", "") for col in df_columns}

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


def try_read_file(content: bytes, filename: str) -> pd.DataFrame:
    """Try to read a file in multiple formats."""
    fname = filename.lower()

    # CSV
    if fname.endswith('.csv'):
        # Try different encodings and separators
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            for sep in [',', ';', '\t', '|']:
                try:
                    df = pd.read_csv(io.BytesIO(content), encoding=encoding, sep=sep)
                    if len(df.columns) > 1:
                        return df
                except:
                    continue
        # Last resort
        return pd.read_csv(io.BytesIO(content), encoding='latin-1')

    # Excel
    if fname.endswith(('.xlsx', '.xls')):
        try:
            xls = pd.ExcelFile(io.BytesIO(content))
            # Read first sheet with data
            for sheet in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet)
                if not df.empty and len(df.columns) > 0:
                    # Skip rows that look like headers/titles (first row all strings, second row has data)
                    return df
            return pd.read_excel(io.BytesIO(content))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error leyendo Excel: {str(e)}")

    # TXT (try as CSV with different separators)
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

    # Smart column mapping
    col_mapping = smart_map_columns(list(df.columns))

    # Rename columns based on mapping
    if col_mapping:
        df = df.rename(columns=col_mapping)
    else:
        # Fallback: normalize column names directly
        df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

    # Check if we found at least a name column - try harder if not
    if "nombre_medico" not in df.columns:
        # If there's a column called just "nombre" or the first string column, use it
        for col in df.columns:
            col_lower = str(col).lower().strip()
            if "nombre" in col_lower or "name" in col_lower or "doctor" in col_lower:
                df = df.rename(columns={col: "nombre_medico"})
                break

    # Still no match? Use the first column that has text data
    if "nombre_medico" not in df.columns:
        for col in df.columns:
            if df[col].dtype == object:  # string column
                sample = df[col].dropna().head(5).tolist()
                if any(isinstance(v, str) and len(v) > 2 for v in sample):
                    df = df.rename(columns={col: "nombre_medico"})
                    break

    if "nombre_medico" not in df.columns:
        # Return helpful error with the columns found
        found_cols = list(df.columns)[:15]
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo identificar la columna de nombres de médicos. Columnas encontradas: {', '.join(str(c) for c in found_cols)}. Asegúrate de que al menos una columna contenga nombres de médicos."
        )

    upload = CardexUpload(filename=file.filename, rows_processed=0)
    db.add(upload)
    db.flush()

    created = 0
    updated = 0
    errors = []
    rep_cache = {}
    bl_cache = {}
    mapped_fields = list(col_mapping.values()) if col_mapping else []

    for idx, row in df.iterrows():
        try:
            name = str(row.get("nombre_medico", "")).strip()
            if not name or name.lower() in ("nan", "", "none", "null"):
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
                        email_gen = f"{rep_name.lower().replace(' ', '.').replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u')}@company.com"
                        rep = MedicalRep(name=rep_name, email=email_gen)
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
            existing = db.query(Doctor).filter(Doctor.name.ilike(f"%{name}%")).first()
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

    return {
        "message": "Cardex cargado exitosamente",
        "upload_id": upload.id,
        "total_rows": len(df),
        "created": created,
        "updated": updated,
        "columns_detected": mapped_fields or [str(c) for c in df.columns],
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
