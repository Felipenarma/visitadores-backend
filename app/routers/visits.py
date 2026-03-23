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
    max_per_day = data.max_per_day if hasattr(data, 'max_per_day') and data.max_per_day else 7
    end_date = datetime.utcnow() + timedelta(days=30 * months_ahead)
    start_date = datetime.utcnow()

    query = db.query(Doctor).filter(Doctor.is_active == True, Doctor.rep_id != None)
    if data.rep_id:
        query = query.filter(Doctor.rep_id == data.rep_id)

    doctors = query.all()

    if not doctors:
        return {"message": "No hay doctores con visitador asignado", "created": 0, "skipped": 0}

    # Group doctors by rep
    from collections import defaultdict
    rep_doctors = defaultdict(list)
    for doc in doctors:
        rep_doctors[doc.rep_id].append(doc)

    total_created = 0
    skipped = 0

    for rep_id, rep_docs in rep_doctors.items():
        # Build a pool of visits needed: each doctor needs visits based on frequency
        visit_pool = []
        for doc in rep_docs:
            freq = doc.visit_frequency if doc.visit_frequency and doc.visit_frequency > 0 else 30
            # Calculate how many visits in the period
            current = start_date
            while current <= end_date:
                # Check if visit already exists
                existing = db.query(Visit).filter(
                    Visit.doctor_id == doc.id,
                    Visit.scheduled_date >= current - timedelta(hours=12),
                    Visit.scheduled_date <= current + timedelta(hours=12)
                ).first()
                if not existing:
                    visit_pool.append({"doctor_id": doc.id, "rep_id": rep_id})
                else:
                    skipped += 1
                current += timedelta(days=freq)

        # Now distribute visits across weekdays (Mon-Fri), max_per_day per day
        current_date = start_date
        pool_idx = 0

        while pool_idx < len(visit_pool) and current_date <= end_date:
            # Skip weekends (5=Saturday, 6=Sunday)
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # Schedule up to max_per_day visits on this day
            day_count = 0
            # Check how many visits already on this day for this rep
            existing_day = db.query(Visit).filter(
                Visit.rep_id == rep_id,
                Visit.scheduled_date >= current_date.replace(hour=0, minute=0, second=0),
                Visit.scheduled_date < current_date.replace(hour=23, minute=59, second=59)
            ).count()
            day_count = existing_day

            while pool_idx < len(visit_pool) and day_count < max_per_day:
                v = visit_pool[pool_idx]
                # Set time slots: 8:00, 9:00, 10:00, etc.
                hour = 8 + day_count
                visit_time = current_date.replace(hour=hour, minute=0, second=0, microsecond=0)

                visit = Visit(
                    doctor_id=v["doctor_id"],
                    rep_id=v["rep_id"],
                    scheduled_date=visit_time,
                    status="scheduled"
                )
                db.add(visit)
                total_created += 1
                day_count += 1
                pool_idx += 1

            current_date += timedelta(days=1)

    db.commit()
    return {
        "message": f"Generación completada: {total_created} visitas creadas, {skipped} ya existentes. Distribuidas en máx {max_per_day} por día (Lun-Vie).",
        "created": total_created,
        "skipped": skipped
    }
