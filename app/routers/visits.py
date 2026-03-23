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
    """
    Generate visits distributed across weekdays.
    - Each doctor gets visited once per frequency cycle
    - Max 7 visits per day per rep (Mon-Fri only)
    - Each doctor only appears ONCE per day
    - Visits are spread evenly across the period
    """
    months_ahead = data.months_ahead or 6
    MAX_PER_DAY = 7
    end_date = datetime.utcnow() + timedelta(days=30 * months_ahead)
    start_date = datetime.utcnow()

    query = db.query(Doctor).filter(Doctor.is_active == True, Doctor.rep_id != None)
    if data.rep_id:
        query = query.filter(Doctor.rep_id == data.rep_id)

    doctors = query.all()

    if not doctors:
        return {"message": "No hay doctores con visitador asignado", "created": 0, "skipped": 0}

    from collections import defaultdict

    # Group doctors by rep
    rep_doctors = defaultdict(list)
    for doc in doctors:
        rep_doctors[doc.rep_id].append(doc)

    total_created = 0

    for rep_id, rep_docs in rep_doctors.items():
        # Build list of available weekdays in the period
        weekdays = []
        d = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while d <= end_date:
            if d.weekday() < 5:  # Mon-Fri
                weekdays.append(d)
            d += timedelta(days=1)

        if not weekdays:
            continue

        # Track how many visits per day and per doctor-per-day
        day_counts = defaultdict(int)       # date -> count
        doc_on_day = defaultdict(set)       # date -> set of doctor_ids

        # For each doctor, schedule visits every N days, spread across weekdays
        # Sort by frequency (most frequent first to ensure they get slots)
        sorted_docs = sorted(rep_docs, key=lambda x: (x.visit_frequency or 30))

        for doc in sorted_docs:
            freq = doc.visit_frequency if doc.visit_frequency and doc.visit_frequency > 0 else 30

            # Find all dates this doctor needs a visit
            next_visit = start_date
            while next_visit <= end_date:
                # Find the nearest weekday with available slots
                # that doesn't already have this doctor
                best_day = None
                for offset in range(0, 7):  # Look up to 7 days ahead
                    candidate = next_visit + timedelta(days=offset)
                    if candidate > end_date:
                        break
                    if candidate.weekday() >= 5:  # Skip weekends
                        continue
                    candidate_date = candidate.replace(hour=0, minute=0, second=0, microsecond=0)
                    if day_counts[candidate_date] < MAX_PER_DAY and doc.id not in doc_on_day[candidate_date]:
                        best_day = candidate_date
                        break

                if best_day:
                    slot_num = day_counts[best_day]
                    hour = 8 + slot_num  # 8:00, 9:00, 10:00...
                    visit_time = best_day.replace(hour=hour)

                    visit = Visit(
                        doctor_id=doc.id,
                        rep_id=rep_id,
                        scheduled_date=visit_time,
                        status="scheduled"
                    )
                    db.add(visit)
                    day_counts[best_day] += 1
                    doc_on_day[best_day].add(doc.id)
                    total_created += 1

                next_visit += timedelta(days=freq)

    db.commit()
    return {
        "message": f"Generación completada: {total_created} visitas creadas. Distribuidas máx {MAX_PER_DAY}/día (Lun-Vie), sin repetir doctor el mismo día.",
        "created": total_created,
    }
