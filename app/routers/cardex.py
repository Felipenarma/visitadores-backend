from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd
import io
from ..database import get_db
from ..models import Doctor, MedicalRep, BusinessLine, CardexUpload

router = APIRouter(prefix="/api/cardex", tags=["cardex"])

TEMPLATE_COLUMNS = [
    "nombre_medico", "especialidad", "direccion", "telefono", "email",
    "nombre_visitador", "linea_negocio", "frecuencia_visita_dias",
    "productos_prescribe", "notas"
]


@router.get("/template")
def download_template():
    df = pd.DataFrame(columns=TEMPLATE_COLUMNS)
    # Add example row
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
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(status_code=400, detail="Formato no soportado. Use CSV o Excel.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al leer archivo: {str(e)}")

    # Normalize column names
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

    # Check required columns
    required = ["nombre_medico"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Columnas faltantes: {', '.join(missing)}"
        )

    upload = CardexUpload(filename=file.filename, rows_processed=len(df))
    db.add(upload)
    db.flush()

    created = 0
    updated = 0
    errors = []
    rep_cache = {}
    bl_cache = {}

    for idx, row in df.iterrows():
        try:
            name = str(row.get("nombre_medico", "")).strip()
            if not name or name.lower() == "nan":
                continue

            specialty = str(row.get("especialidad", "")).strip() if pd.notna(row.get("especialidad")) else None
            address = str(row.get("direccion", "")).strip() if pd.notna(row.get("direccion")) else None
            phone = str(row.get("telefono", "")).strip() if pd.notna(row.get("telefono")) else None
            email = str(row.get("email", "")).strip() if pd.notna(row.get("email")) else None
            rep_name = str(row.get("nombre_visitador", "")).strip() if pd.notna(row.get("nombre_visitador")) else None
            bl_name = str(row.get("linea_negocio", "")).strip() if pd.notna(row.get("linea_negocio")) else None
            freq_raw = row.get("frecuencia_visita_dias", 30)
            prescribes = str(row.get("productos_prescribe", "")).strip() if pd.notna(row.get("productos_prescribe")) else None
            notes = str(row.get("notas", "")).strip() if pd.notna(row.get("notas")) else None

            try:
                frequency = int(freq_raw) if freq_raw and str(freq_raw) != "nan" else 30
            except (ValueError, TypeError):
                frequency = 30

            # Find or create rep
            rep_id = None
            if rep_name and rep_name.lower() != "nan":
                if rep_name not in rep_cache:
                    rep = db.query(MedicalRep).filter(MedicalRep.name.ilike(rep_name)).first()
                    if not rep:
                        rep = MedicalRep(name=rep_name, email=f"{rep_name.lower().replace(' ', '.')}@company.com")
                        db.add(rep)
                        db.flush()
                    rep_cache[rep_name] = rep.id
                rep_id = rep_cache[rep_name]

            # Find or create business line
            bl_id = None
            if bl_name and bl_name.lower() != "nan":
                if bl_name not in bl_cache:
                    bl = db.query(BusinessLine).filter(BusinessLine.name.ilike(bl_name)).first()
                    if not bl:
                        bl = BusinessLine(name=bl_name)
                        db.add(bl)
                        db.flush()
                    bl_cache[bl_name] = bl.id
                bl_id = bl_cache[bl_name]

            # Find or create doctor
            existing = db.query(Doctor).filter(Doctor.name.ilike(name)).first()
            if existing:
                existing.specialty = specialty or existing.specialty
                existing.address = address or existing.address
                existing.phone = phone or existing.phone
                existing.email = email or existing.email
                existing.rep_id = rep_id or existing.rep_id
                existing.business_line_id = bl_id or existing.business_line_id
                existing.visit_frequency = frequency
                existing.prescribes_products = prescribes or existing.prescribes_products
                existing.notes = notes or existing.notes
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
                    notes=notes
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
        "errors": errors[:10]
    }
