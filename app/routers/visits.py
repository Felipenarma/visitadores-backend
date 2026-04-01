from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from ..database import get_db
from ..models import Visit, Doctor, MedicalRep
from ..schemas import VisitCreate, VisitUpdate, VisitOut, GenerateVisitsRequest

router = APIRouter(prefix="/api/visits", tags=["visits"])


def enrich_visit(visit: Visit) -> VisitOut:
    out = VisitOut.model_validate(visit)
    if visit.doctor:
        out.doctor_name = visit.doctor.name
        out.doctor_specialty = visit.doctor.specialty
    if visit.rep:
        out.rep_name = visit.rep.name
    return out


@router.get("/", response_model=List[VisitOut])
def get_visits(
    rep_id: Optional[int] = Query(None),
    doctor_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Visit)
    if rep_id is not None:
        query = query.filter(Visit.rep_id == rep_id)
    if doctor_id is not None:
        query = query.filter(Visit.doctor_id == doctor_id)
    if status is not None:
        query = query.filter(Visit.status == status)
    if date_from is not None:
        query = query.filter(Visit.scheduled_date >= date_from)
    if date_to is not None:
        query = query.filter(Visit.scheduled_date <= date_to)

    visits = query.order_by(Visit.scheduled_date.asc()).all()
    return [enrich_visit(v) for v in visits]


@router.get("/{visit_id}", response_model=VisitOut)
def get_visit(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")
    return enrich_visit(visit)


@router.post("/", response_model=VisitOut)
def create_visit(data: VisitCreate, db: Session = Depends(get_db)):
    doctor = db.query(Doctor).filter(Doctor.id == data.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Médico no encontrado")
    rep = db.query(MedicalRep).filter(MedicalRep.id == data.rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")

    visit = Visit(**data.model_dump())
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return enrich_visit(visit)


@router.put("/{visit_id}", response_model=VisitOut)
def update_visit(visit_id: int, data: VisitUpdate, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(visit, key, value)
    if data.status == "completed" and not visit.actual_date:
        visit.actual_date = datetime.utcnow()
    db.commit()
    db.refresh(visit)
    return enrich_visit(visit)


@router.delete("/clear-scheduled")
def clear_scheduled_visits(rep_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Delete all scheduled visits. Optionally filter by rep_id."""
    query = db.query(Visit).filter(Visit.status == "scheduled")
    if rep_id is not None:
        query = query.filter(Visit.rep_id == rep_id)
    count = query.delete(synchronize_session=False)
    db.commit()
    return {"message": f"{count} visitas agendadas eliminadas", "deleted": count}


@router.delete("/{visit_id}")
def delete_visit(visit_id: int, db: Session = Depends(get_db)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visita no encontrada")
    db.delete(visit)
    db.commit()
    return {"message": "Visita eliminada"}


@router.post("/generate")
def generate_visits(data: GenerateVisitsRequest, db: Session = Depends(get_db)):
    months_ahead = data.months_ahead or 6
    end_date = datetime.utcnow() + timedelta(days=30 * months_ahead)
    start_date = datetime.utcnow()

    query = db.query(Doctor).filter(Doctor.is_active == True, Doctor.rep_id != None)
    if data.rep_id:
        query = query.filter(Doctor.rep_id == data.rep_id)

    doctors = query.all()
    total_created = 0
    skipped = 0

    for doctor in doctors:
        if not doctor.visit_frequency or doctor.visit_frequency <= 0:
            continue

        # Find last scheduled or completed visit
        last_visit = db.query(Visit).filter(
            Visit.doctor_id == doctor.id,
            Visit.scheduled_date >= start_date
        ).order_by(Visit.scheduled_date.desc()).first()

        if last_visit:
            # Start from after the last scheduled visit
            next_date = last_visit.scheduled_date + timedelta(days=doctor.visit_frequency)
        else:
            next_date = start_date

        while next_date <= end_date:
            # Check if visit already exists on this date (within 1 day)
            existing = db.query(Visit).filter(
                Visit.doctor_id == doctor.id,
                Visit.scheduled_date >= next_date - timedelta(hours=12),
                Visit.scheduled_date <= next_date + timedelta(hours=12)
            ).first()

            if not existing:
                visit = Visit(
                    doctor_id=doctor.id,
                    rep_id=doctor.rep_id,
                    scheduled_date=next_date,
                    status="scheduled"
                )
                db.add(visit)
                total_created += 1
            else:
                skipped += 1

            next_date += timedelta(days=doctor.visit_frequency)

    db.commit()
    return {
        "message": f"Generación completada: {total_created} visitas creadas, {skipped} ya existentes",
        "created": total_created,
        "skipped": skipped
    }
