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


def match_doctor(name: str, db: Session) -> Optional[Doctor]:
    """Try to match a doctor by name (fuzzy)."""
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

    required_cols = ["nombre_medico", "producto", "monto", "fecha_venta"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        # Try alternative column names
        col_map = {
            "doctor": "nombre_medico", "medico": "nombre_medico", "name": "nombre_medico",
            "product": "producto", "amount": "monto", "total": "monto",
            "date": "fecha_venta", "fecha": "fecha_venta", "sale_date": "fecha_venta"
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Columnas faltantes: {', '.join(missing)}. Columnas requeridas: {', '.join(required_cols)}"
            )

    upload = SalesUpload(filename=file.filename, rows_processed=len(df))
    db.add(upload)
    db.flush()

    matched = 0
    unmatched = 0
    errors = []

    for _, row in df.iterrows():
        try:
            doctor_name = str(row.get("nombre_medico", "")).strip()
            product = str(row.get("producto", "")).strip()
            amount_raw = row.get("monto", 0)
            date_raw = row.get("fecha_venta", None)

            try:
                amount = float(amount_raw) if amount_raw else 0.0
            except (ValueError, TypeError):
                amount = 0.0

            sale_date = None
            if date_raw:
                try:
                    sale_date = pd.to_datetime(date_raw).to_pydatetime()
                except Exception:
                    sale_date = None

            doctor = match_doctor(doctor_name, db)

            sale = Sale(
                doctor_id=doctor.id if doctor else None,
                doctor_name_raw=doctor_name,
                product=product,
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
        total_sales = db.query(func.sum(Sale.amount)).filter(Sale.doctor_id == doctor.id).scalar() or 0
        sales_count = db.query(func.count(Sale.id)).filter(Sale.doctor_id == doctor.id).scalar()
        visits_count = db.query(func.count(Visit.id)).filter(
            Visit.doctor_id == doctor.id,
            Visit.status == "completed"
        ).scalar()

        item = SalesSummaryItem(
            doctor_id=doctor.id,
            doctor_name=doctor.name,
            total_sales=total_sales,
            sales_count=sales_count,
            visits_count=visits_count,
            has_visits=visits_count > 0
        )
        result.append(item)

    result.sort(key=lambda x: x.total_sales, reverse=True)
    return result
