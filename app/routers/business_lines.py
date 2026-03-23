from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from ..database import get_db
from ..models import BusinessLine, Doctor
from ..schemas import BusinessLineCreate, BusinessLineUpdate, BusinessLineOut

router = APIRouter(prefix="/api/business-lines", tags=["business_lines"])


@router.get("/", response_model=List[BusinessLineOut])
def get_business_lines(db: Session = Depends(get_db)):
    lines = db.query(BusinessLine).all()
    result = []
    for line in lines:
        count = db.query(func.count(Doctor.id)).filter(
            Doctor.business_line_id == line.id,
            Doctor.is_active == True
        ).scalar()
        out = BusinessLineOut.model_validate(line)
        out.doctor_count = count
        result.append(out)
    return result


@router.post("/", response_model=BusinessLineOut)
def create_business_line(data: BusinessLineCreate, db: Session = Depends(get_db)):
    existing = db.query(BusinessLine).filter(BusinessLine.name == data.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe una línea de negocio con ese nombre")
    line = BusinessLine(**data.model_dump())
    db.add(line)
    db.commit()
    db.refresh(line)
    out = BusinessLineOut.model_validate(line)
    out.doctor_count = 0
    return out


@router.put("/{line_id}", response_model=BusinessLineOut)
def update_business_line(line_id: int, data: BusinessLineUpdate, db: Session = Depends(get_db)):
    line = db.query(BusinessLine).filter(BusinessLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Línea de negocio no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(line, key, value)
    db.commit()
    db.refresh(line)
    count = db.query(func.count(Doctor.id)).filter(
        Doctor.business_line_id == line.id,
        Doctor.is_active == True
    ).scalar()
    out = BusinessLineOut.model_validate(line)
    out.doctor_count = count
    return out


@router.delete("/{line_id}")
def delete_business_line(line_id: int, db: Session = Depends(get_db)):
    line = db.query(BusinessLine).filter(BusinessLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Línea de negocio no encontrada")
    # Check if any doctors use this line
    count = db.query(func.count(Doctor.id)).filter(Doctor.business_line_id == line_id).scalar()
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: {count} médico(s) están asignados a esta línea"
        )
    db.delete(line)
    db.commit()
    return {"message": "Línea de negocio eliminada"}
