from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from ..database import get_db
from ..models import Doctor, MedicalRep, BusinessLine, Visit, Sale
from ..schemas import DoctorCreate, DoctorUpdate, DoctorOut, AssignRepRequest

router = APIRouter(prefix="/api/doctors", tags=["doctors"])


def enrich_doctor(doctor: Doctor, db: Session) -> DoctorOut:
    out = DoctorOut.model_validate(doctor)
    if doctor.business_line:
        out.business_line_name = doctor.business_line.name
    if doctor.rep:
        out.rep_name = doctor.rep.name

    last_visit = db.query(Visit).filter(
        Visit.doctor_id == doctor.id,
        Visit.status == "completed"
    ).order_by(Visit.actual_date.desc()).first()
    if last_visit:
        out.last_visit_date = last_visit.actual_date

    visit_count = db.query(func.count(Visit.id)).filter(Visit.doctor_id == doctor.id).scalar()
    out.visits_count = visit_count

    sale_count = db.query(func.count(Sale.id)).filter(Sale.doctor_id == doctor.id).scalar()
    out.has_sales = sale_count > 0

    return out


@router.get("/", response_model=List[DoctorOut])
def get_doctors(
    rep_id: Optional[int] = Query(None),
    business_line_id: Optional[int] = Query(None),
    specialty: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    has_sales: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Doctor)
    if rep_id is not None:
        query = query.filter(Doctor.rep_id == rep_id)
    if business_line_id is not None:
        query = query.filter(Doctor.business_line_id == business_line_id)
    if specialty is not None:
        query = query.filter(Doctor.specialty.ilike(f"%{specialty}%"))
    if is_active is not None:
        query = query.filter(Doctor.is_active == is_active)
    if search:
        query = query.filter(Doctor.name.ilike(f"%{search}%"))

    doctors = query.all()

    if has_sales is not None:
        result = []
        for doc in doctors:
            sale_count = db.query(func.count(Sale.id)).filter(Sale.doctor_id == doc.id).scalar()
            if has_sales and sale_count > 0:
                result.append(enrich_doctor(doc, db))
            elif not has_sales and sale_count == 0:
                result.append(enrich_doctor(doc, db))
        return result

    return [enrich_doctor(doc, db) for doc in doctors]


@router.get("/{doctor_id}", response_model=DoctorOut)
def get_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Médico no encontrado")
    return enrich_doctor(doctor, db)


@router.post("/", response_model=DoctorOut)
def create_doctor(data: DoctorCreate, db: Session = Depends(get_db)):
    if data.rep_id:
        rep = db.query(MedicalRep).filter(MedicalRep.id == data.rep_id).first()
        if not rep:
            raise HTTPException(status_code=404, detail="Visitador no encontrado")
    if data.business_line_id:
        bl = db.query(BusinessLine).filter(BusinessLine.id == data.business_line_id).first()
        if not bl:
            raise HTTPException(status_code=404, detail="Línea de negocio no encontrada")

    doctor = Doctor(**data.model_dump())
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return enrich_doctor(doctor, db)


@router.put("/{doctor_id}", response_model=DoctorOut)
def update_doctor(doctor_id: int, data: DoctorUpdate, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Médico no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(doctor, key, value)
    db.commit()
    db.refresh(doctor)
    return enrich_doctor(doctor, db)


@router.delete("/{doctor_id}")
def delete_doctor(doctor_id: int, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Médico no encontrado")
    doctor.is_active = False
    db.commit()
    return {"message": "Médico desactivado"}


@router.put("/{doctor_id}/assign-rep", response_model=DoctorOut)
def assign_rep(doctor_id: int, data: AssignRepRequest, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Médico no encontrado")
    rep = db.query(MedicalRep).filter(MedicalRep.id == data.rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")
    doctor.rep_id = data.rep_id
    db.commit()
    db.refresh(doctor)
    return enrich_doctor(doctor, db)
