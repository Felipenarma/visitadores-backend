from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from ..database import get_db
from ..models import Doctor, MedicalRep, Visit, Sale, BusinessLine
from ..schemas import DashboardStats, RepStats

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    week_end = week_start + timedelta(days=7)

    total_doctors = db.query(func.count(Doctor.id)).filter(Doctor.is_active == True).scalar()
    active_reps = db.query(func.count(MedicalRep.id)).filter(MedicalRep.is_active == True).scalar()
    visits_today = db.query(func.count(Visit.id)).filter(
        Visit.scheduled_date >= today_start,
        Visit.scheduled_date < today_end
    ).scalar()
    visits_this_week = db.query(func.count(Visit.id)).filter(
        Visit.scheduled_date >= week_start,
        Visit.scheduled_date < week_end
    ).scalar()
    total_visits = db.query(func.count(Visit.id)).scalar()
    completed_visits = db.query(func.count(Visit.id)).filter(Visit.status == "completed").scalar()
    missed_visits = db.query(func.count(Visit.id)).filter(Visit.status == "missed").scalar()

    return DashboardStats(
        total_doctors=total_doctors,
        active_reps=active_reps,
        visits_today=visits_today,
        visits_this_week=visits_this_week,
        total_visits=total_visits,
        completed_visits=completed_visits,
        missed_visits=missed_visits
    )


@router.get("/today")
def get_today_visits(db: Session = Depends(get_db)):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    visits = db.query(Visit).filter(
        Visit.scheduled_date >= today_start,
        Visit.scheduled_date < today_end
    ).all()

    result = []
    for v in visits:
        result.append({
            "visit_id": v.id,
            "doctor_name": v.doctor.name if v.doctor else "N/A",
            "doctor_specialty": v.doctor.specialty if v.doctor else None,
            "rep_name": v.rep.name if v.rep else "N/A",
            "rep_id": v.rep_id,
            "scheduled_date": v.scheduled_date.isoformat() if v.scheduled_date else None,
            "status": v.status,
            "notes": v.notes
        })
    return result


@router.get("/visits-by-rep")
def get_visits_by_rep(db: Session = Depends(get_db)):
    reps = db.query(MedicalRep).filter(MedicalRep.is_active == True).all()
    result = []
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    for rep in reps:
        count = db.query(func.count(Visit.id)).filter(
            Visit.rep_id == rep.id,
            Visit.scheduled_date >= month_start
        ).scalar()
        result.append({"rep_name": rep.name, "visits": count, "rep_id": rep.id})
    return result


@router.get("/sales-by-business-line")
def get_sales_by_business_line(db: Session = Depends(get_db)):
    bls = db.query(BusinessLine).all()
    result = []
    for bl in bls:
        # Sum sales for doctors in this business line
        total = db.query(func.sum(Sale.amount)).join(
            Doctor, Sale.doctor_id == Doctor.id
        ).filter(Doctor.business_line_id == bl.id).scalar() or 0
        result.append({"name": bl.name, "value": total, "color": bl.color})
    return result


@router.get("/rep/{rep_id}/stats")
def get_rep_stats(rep_id: int, db: Session = Depends(get_db)):
    rep = db.query(MedicalRep).filter(MedicalRep.id == rep_id).first()
    if not rep:
        return {"error": "Visitador no encontrado"}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    week_end = week_start + timedelta(days=7)
    month_start = today_start.replace(day=1)

    doctor_count = db.query(func.count(Doctor.id)).filter(
        Doctor.rep_id == rep_id, Doctor.is_active == True
    ).scalar()
    visits_today = db.query(func.count(Visit.id)).filter(
        Visit.rep_id == rep_id,
        Visit.scheduled_date >= today_start,
        Visit.scheduled_date < today_end
    ).scalar()
    visits_week = db.query(func.count(Visit.id)).filter(
        Visit.rep_id == rep_id,
        Visit.scheduled_date >= week_start,
        Visit.scheduled_date < week_end
    ).scalar()
    completed_month = db.query(func.count(Visit.id)).filter(
        Visit.rep_id == rep_id,
        Visit.status == "completed",
        Visit.scheduled_date >= month_start
    ).scalar()
    missed_month = db.query(func.count(Visit.id)).filter(
        Visit.rep_id == rep_id,
        Visit.status == "missed",
        Visit.scheduled_date >= month_start
    ).scalar()

    # Upcoming visits this week
    upcoming = db.query(Visit).filter(
        Visit.rep_id == rep_id,
        Visit.scheduled_date >= today_start,
        Visit.scheduled_date < week_end,
        Visit.status == "scheduled"
    ).order_by(Visit.scheduled_date.asc()).all()

    upcoming_list = []
    for v in upcoming:
        upcoming_list.append({
            "visit_id": v.id,
            "doctor_name": v.doctor.name if v.doctor else "N/A",
            "doctor_specialty": v.doctor.specialty if v.doctor else None,
            "scheduled_date": v.scheduled_date.isoformat() if v.scheduled_date else None,
            "status": v.status
        })

    return {
        "rep_id": rep_id,
        "rep_name": rep.name,
        "doctor_count": doctor_count,
        "visits_today": visits_today,
        "visits_this_week": visits_week,
        "completed_this_month": completed_month,
        "missed_this_month": missed_month,
        "upcoming_visits": upcoming_list
    }
