from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
import pandas as pd
import io
from datetime import datetime
from ..database import get_db
from ..models import Sale, SalesUpload, Doctor, Visit
from ..schemas import SaleOut, SalesSummaryItem

router = APIRouter(prefix="/api/sales", tags=["sales"])


def match_doctor_by_rut(rut: str, db: Session) -> Optional[Doctor]:
    """Match a doctor by RUT."""
    if not rut:
        return None
    rut = rut.strip().replace(".", "").replace("-", "").upper()
    doctors = db.query(Doctor).filter(Doctor.rut.isnot(None)).all()
    for doc in doctors:
        doc_rut = doc.rut.strip().replace(".", "").replace("-", "").upper() if doc.rut else ""
        if doc_rut == rut:
            return doc
    return None


def match_doctor(name: str, db: Session, rut: str = None) -> Optional[Doctor]:
    """Try to match a doctor by RUT first, then by name (fuzzy)."""
    # Try RUT first
    if rut:
        doc = match_doctor_by_rut(rut, db)
        if doc:
            return doc

    if not name:
        return None
    name = name.strip().lower()
    doctors = db.query(Doctor).filter(Doctor.is_active == True).all()
    for doc in doctors:
        if doc.name.lower() == name:
            return doc
    # partial match
    for doc in doctors:
        if name in doc.name.lower() or doc.name.lower() in name:
            return doc
    return None


@router.get("/", response_model=List[SaleOut])
def get_sales(db: Session = Depends(get_db)):
    sales = db.query(Sale).order_by(Sale.created_at.desc()).limit(500).all()
    result = []
    for sale in sales:
        out = SaleOut.model_validate(sale)
        if sale.doctor:
            out.doctor_name = sale.doctor.name
        result.append(out)
    return result


@router.post("/upload")
async def upload_sales(file: UploadFile = File(...), db: Session = Depends(get_db)):
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

    # Try alternative column names
    col_map = {
        "doctor": "nombre_medico", "medico": "nombre_medico", "name": "nombre_medico",
        "nombre": "nombre_medico", "nombre_doctor": "nombre_medico",
        "product": "producto", "amount": "monto", "total": "monto",
        "precio_total": "monto", "precio_receta": "monto",
        "date": "fecha_venta", "fecha": "fecha_venta", "sale_date": "fecha_venta",
        "fecha_ingresado": "fecha_venta",
        "rut_medico": "rut", "rut_doctor": "rut", "run": "rut",
        "categoria": "category",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # At minimum we need doctor identification
    has_doctor_id = "rut" in df.columns or "nombre_medico" in df.columns
    if not has_doctor_id:
        raise HTTPException(
            status_code=400,
            detail=f"Se necesita al menos una columna 'rut' o 'nombre_medico' para identificar al médico. Columnas encontradas: {', '.join(df.columns)}"
        )

    upload = SalesUpload(filename=file.filename, rows_processed=len(df))
    db.add(upload)
    db.flush()

    matched = 0
    unmatched = 0
    errors = []

    for _, row in df.iterrows():
        try:
            doctor_name = str(row.get("nombre_medico", "")).strip() if "nombre_medico" in row else ""
            doctor_rut = str(row.get("rut", "")).strip() if "rut" in row else ""
            product = str(row.get("producto", "")).strip() if "producto" in row else ""
            category = str(row.get("category", "")).strip() if "category" in row else ""
            amount_raw = row.get("monto", 0)
            quantity_raw = row.get("cantidad", 1)
            date_raw = row.get("fecha_venta", None)

            try:
                amount = float(amount_raw) if pd.notna(amount_raw) else 0.0
            except (ValueError, TypeError):
                amount = 0.0

            try:
                quantity = int(float(str(quantity_raw))) if pd.notna(quantity_raw) else 1
            except (ValueError, TypeError):
                quantity = 1

            sale_date = None
            if date_raw:
                try:
                    sale_date = pd.to_datetime(date_raw).to_pydatetime()
                except Exception:
                    sale_date = None

            doctor = match_doctor(doctor_name, db, rut=doctor_rut)

            sale = Sale(
                doctor_id=doctor.id if doctor else None,
                doctor_name_raw=doctor_name,
                doctor_rut_raw=doctor_rut if doctor_rut else None,
                product=product,
                category=category if category and category != 'nan' else None,
                quantity=quantity,
                amount=amount,
                sale_date=sale_date,
                upload_id=upload.id
            )
            db.add(sale)
            if doctor:
                matched += 1
            else:
                unmatched += 1
        except Exception as e:
            errors.append(str(e))

    db.commit()

    return {
        "message": "Ventas cargadas exitosamente",
        "upload_id": upload.id,
        "rows_processed": len(df),
        "matched_doctors": matched,
        "unmatched_doctors": unmatched,
        "errors": errors[:10]
    }


@router.get("/summary")
def get_sales_summary(db: Session = Depends(get_db)):
    doctors = db.query(Doctor).filter(Doctor.is_active == True).all()
    result = []

    for doctor in doctors:
        total_units = db.query(func.sum(Sale.quantity)).filter(Sale.doctor_id == doctor.id).scalar() or 0
        total_sales = db.query(func.sum(Sale.amount)).filter(Sale.doctor_id == doctor.id).scalar() or 0
        sales_count = db.query(func.count(Sale.id)).filter(Sale.doctor_id == doctor.id).scalar()
        visits_count = db.query(func.count(Visit.id)).filter(
            Visit.doctor_id == doctor.id,
            Visit.status == "completed"
        ).scalar()

        item = SalesSummaryItem(
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            doctor_rut=doctor.rut,
            total_units=int(total_units),
            total_sales=total_sales,
            sales_count=sales_count,
            visits_count=visits_count,
            has_visits=visits_count > 0
        )
        result.append(item)

    result.sort(key=lambda x: x.total_sales, reverse=True)
    return result
