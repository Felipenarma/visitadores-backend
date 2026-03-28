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


@router.delete("/clear-scheduled")
def clear_scheduled_visits(rep_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Delete all scheduled visits (not completed/missed). Optionally filter by rep_id."""
    query = db.query(Visit).filter(Visit.status == "scheduled")
    if rep_id is not None:
        query = query.filter(Visit.rep_id == rep_id)
    count = query.delete(synchronize_session=False)
    db.commit()
    return {"message": f"{count} visitas agendadas eliminadas", "deleted": count}


@router.post("/generate")
def generate_visits(data: GenerateVisitsRequest, db: Session = Depends(get_db)):
    """
    Generate visits distributed across weekdays.
    - All doctors are spread evenly across weekdays (7 per day, Mon-Fri)
    - Each cycle covers all doctors, then repeats based on frequency
    - No doctor appears twice on the same day
    """
    months_ahead = data.months_ahead or 6
    MAX_PER_DAY = 7
    if data.start_date:
        start_date = datetime.fromisoformat(data.start_date)
    else:
        start_date = datetime.utcnow()
    end_date = start_date + timedelta(days=30 * months_ahead)

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

        # Sort doctors by zone (notes field) so same-zone doctors are grouped together
        # This ensures each day's visits are geographically clustered
        rep_docs_sorted = sorted(rep_docs, key=lambda doc: (doc.notes or 'ZZZ_sin_zona'))

        # Group doctors by frequency
        freq_groups = defaultdict(list)
        for doc in rep_docs_sorted:
            freq = doc.visit_frequency if doc.visit_frequency and doc.visit_frequency > 0 else 30
            freq_groups[freq].append(doc)

        day_counts = defaultdict(int)  # date -> count of visits
        doc_on_day = defaultdict(set)  # date -> set of doctor_ids

        for freq, docs_in_group in freq_groups.items():
            # Calculate how many cycles fit in the period
            total_days = (end_date - start_date).days
            num_cycles = max(1, total_days // freq)

            for cycle in range(num_cycles):
                # Start date of this cycle
                cycle_start_day = start_date + timedelta(days=cycle * freq)
                if cycle_start_day > end_date:
                    break

                # Get weekdays available from cycle_start
                cycle_weekdays = [wd for wd in weekdays if wd >= cycle_start_day.replace(hour=0, minute=0, second=0, microsecond=0)]

                # Distribute doctors grouped by zone across weekdays
                # Same-zone doctors fill a day before moving to next zone/day
                doc_idx = 0
                for wd in cycle_weekdays:
                    if doc_idx >= len(docs_in_group):
                        break  # All doctors in this cycle scheduled

                    while doc_idx < len(docs_in_group) and day_counts[wd] < MAX_PER_DAY:
                        doc = docs_in_group[doc_idx]

                        # Skip if this doctor already has a visit on this day
                        if doc.id in doc_on_day[wd]:
                            doc_idx += 1
                            continue

                        slot_num = day_counts[wd]
                        hour = 8 + slot_num  # 8:00, 9:00, 10:00...
                        visit_time = wd.replace(hour=hour)

                        visit = Visit(
                            doctor_id=doc.id,
                            rep_id=rep_id,
                            scheduled_date=visit_time,
                            status="scheduled"
                        )
                        db.add(visit)
                        day_counts[wd] += 1
                        doc_on_day[wd].add(doc.id)
                        total_created += 1
                        doc_idx += 1

    db.commit()
    return {
        "message": f"Generación completada: {total_created} visitas creadas. Distribuidas máx {MAX_PER_DAY}/día (Lun-Vie).",
        "created": total_created,
    }
