from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from ..database import get_db
from ..models import MedicalRep, Doctor
from ..schemas import MedicalRepCreate, MedicalRepUpdate, MedicalRepOut

router = APIRouter(prefix="/api/reps", tags=["reps"])


@router.get("/", response_model=List[MedicalRepOut])
def get_reps(db: Session = Depends(get_db)):
    reps = db.query(MedicalRep).all()
    result = []
    for rep in reps:
        count = db.query(func.count(Doctor.id)).filter(
            Doctor.rep_id == rep.id,
            Doctor.is_active == True
        ).scalar()
        out = MedicalRepOut.model_validate(rep)
        out.doctor_count = count
        result.append(out)
    return result


@router.get("/{rep_id}", response_model=MedicalRepOut)
def get_rep(rep_id: int, db: Session = Depends(get_db)):
    rep = db.query(MedicalRep).filter(MedicalRep.id == rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")
    count = db.query(func.count(Doctor.id)).filter(
        Doctor.rep_id == rep.id,
        Doctor.is_active == True
    ).scalar()
    out = MedicalRepOut.model_validate(rep)
    out.doctor_count = count
    return out


@router.post("/", response_model=MedicalRepOut)
def create_rep(data: MedicalRepCreate, db: Session = Depends(get_db)):
    existing = db.query(MedicalRep).filter(MedicalRep.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un visitador con ese email")
    rep = MedicalRep(**data.model_dump())
    db.add(rep)
    db.commit()
    db.refresh(rep)
    out = MedicalRepOut.model_validate(rep)
    out.doctor_count = 0
    return out


@router.put("/{rep_id}", response_model=MedicalRepOut)
def update_rep(rep_id: int, data: MedicalRepUpdate, db: Session = Depends(get_db)):
    rep = db.query(MedicalRep).filter(MedicalRep.id == rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(rep, key, value)
    db.commit()
    db.refresh(rep)
    count = db.query(func.count(Doctor.id)).filter(
        Doctor.rep_id == rep.id,
        Doctor.is_active == True
    ).scalar()
    out = MedicalRepOut.model_validate(rep)
    out.doctor_count = count
    return out


@router.delete("/{rep_id}")
def delete_rep(rep_id: int, db: Session = Depends(get_db)):
    rep = db.query(MedicalRep).filter(MedicalRep.id == rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")
    count = db.query(func.count(Doctor.id)).filter(Doctor.rep_id == rep_id).scalar()
    if count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"No se puede eliminar: {count} médico(s) están asignados a este visitador"
        )
    db.delete(rep)
    db.commit()
    return {"message": "Visitador eliminado"}
