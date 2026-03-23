from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import random

from .database import engine, get_db, Base
from .models import BusinessLine, MedicalRep, Doctor, Visit, Sale
from .routers import business_lines, reps, doctors, visits, sales, cardex, dashboard, ai_agent, knowledge

# Create tables (checkfirst=True avoids errors if tables already exist)
Base.metadata.create_all(bind=engine, checkfirst=True)

app = FastAPI(title="Visitadores Médicos API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(business_lines.router)
app.include_router(reps.router)
app.include_router(doctors.router)
app.include_router(visits.router)
app.include_router(sales.router)
app.include_router(cardex.router)
app.include_router(dashboard.router)
app.include_router(ai_agent.router)
app.include_router(knowledge.router)


def seed_business_lines(db: Session):
    default_lines = [
        {"name": "Cannabis Medicinal", "description": "Productos de cannabis medicinal", "color": "#10B981"},
        {"name": "Hormonas", "description": "Tratamientos hormonales", "color": "#8B5CF6"},
        {"name": "Dermatología", "description": "Productos dermatológicos", "color": "#F59E0B"},
        {"name": "Control de Peso", "description": "Soluciones para control de peso", "color": "#EF4444"},
        {"name": "Suero Terapia", "description": "Terapias con sueros", "color": "#3B82F6"},
    ]
    for line_data in default_lines:
        existing = db.query(BusinessLine).filter(BusinessLine.name == line_data["name"]).first()
        if not existing:
            line = BusinessLine(**line_data)
            db.add(line)
    db.commit()


@app.on_event("startup")
def startup_event():
    db = next(get_db())
    try:
        seed_business_lines(db)
    finally:
        db.close()


@app.get("/")
def root():
    return {"message": "Visitadores Médicos API", "version": "1.0.0", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/seed")
def seed_sample_data(db: Session = Depends(get_db)):
    """Seed sample data for testing."""
    # Create sample reps
    rep_data = [
        {"name": "María González", "email": "maria@pharma.com", "phone": "555-0001", "territory": "Norte", "zone": "CDMX"},
        {"name": "Carlos Ramírez", "email": "carlos@pharma.com", "phone": "555-0002", "territory": "Sur", "zone": "Guadalajara"},
        {"name": "Ana Martínez", "email": "ana@pharma.com", "phone": "555-0003", "territory": "Centro", "zone": "Monterrey"},
    ]

    reps = []
    for data in rep_data:
        existing = db.query(MedicalRep).filter(MedicalRep.email == data["email"]).first()
        if not existing:
            rep = MedicalRep(**data)
            db.add(rep)
            db.flush()
            reps.append(rep)
        else:
            reps.append(existing)

    business_lines = db.query(BusinessLine).all()
    bl_map = {bl.name: bl for bl in business_lines}

    specialties = ["Dermatología", "Endocrinología", "Medicina General", "Ginecología", "Oncología", "Neurología"]
    doctor_data = [
        {"name": "Dr. Juan Pérez", "specialty": "Dermatología", "phone": "555-1001", "visit_frequency": 30},
        {"name": "Dra. Laura Sánchez", "specialty": "Endocrinología", "phone": "555-1002", "visit_frequency": 14},
        {"name": "Dr. Roberto Flores", "specialty": "Medicina General", "phone": "555-1003", "visit_frequency": 21},
        {"name": "Dra. Carmen López", "specialty": "Ginecología", "phone": "555-1004", "visit_frequency": 30},
        {"name": "Dr. Miguel Torres", "specialty": "Oncología", "phone": "555-1005", "visit_frequency": 7},
        {"name": "Dra. Patricia Ruiz", "specialty": "Neurología", "phone": "555-1006", "visit_frequency": 14},
        {"name": "Dr. Alejandro Morales", "specialty": "Dermatología", "phone": "555-1007", "visit_frequency": 30},
        {"name": "Dra. Sofía Herrera", "specialty": "Endocrinología", "phone": "555-1008", "visit_frequency": 21},
        {"name": "Dr. Fernando Castro", "specialty": "Medicina General", "phone": "555-1009", "visit_frequency": 30},
        {"name": "Dra. Isabel Díaz", "specialty": "Ginecología", "phone": "555-1010", "visit_frequency": 14},
    ]

    bl_list = list(bl_map.values())
    doctors = []
    for i, data in enumerate(doctor_data):
        existing = db.query(Doctor).filter(Doctor.name == data["name"]).first()
        if not existing:
            bl = bl_list[i % len(bl_list)] if bl_list else None
            rep = reps[i % len(reps)] if reps else None
            doc = Doctor(
                name=data["name"],
                specialty=data["specialty"],
                phone=data["phone"],
                address=f"Calle {i+1} No. {100+i}, Col. Centro",
                visit_frequency=data["visit_frequency"],
                business_line_id=bl.id if bl else None,
                rep_id=rep.id if rep else None,
                prescribes_products=f"Producto {chr(65+i)}, Producto {chr(66+i)}"
            )
            db.add(doc)
            db.flush()
            doctors.append(doc)
        else:
            doctors.append(existing)

    # Create visits for past 3 months and next 3 months
    now = datetime.utcnow()
    visits_created = 0
    for doc in doctors:
        if not doc.rep_id or not doc.visit_frequency:
            continue
        freq = doc.visit_frequency
        # Past visits
        date = now - timedelta(days=90)
        while date < now:
            statuses = ["completed", "completed", "completed", "missed"]
            visit = Visit(
                doctor_id=doc.id,
                rep_id=doc.rep_id,
                scheduled_date=date,
                actual_date=date if random.choice([True, True, False]) else None,
                status=random.choice(statuses),
                notes="Visita registrada" if random.choice([True, False]) else None
            )
            db.add(visit)
            visits_created += 1
            date += timedelta(days=freq)
        # Future visits
        date = now + timedelta(days=freq)
        end = now + timedelta(days=90)
        while date < end:
            visit = Visit(
                doctor_id=doc.id,
                rep_id=doc.rep_id,
                scheduled_date=date,
                status="scheduled"
            )
            db.add(visit)
            visits_created += 1
            date += timedelta(days=freq)

    db.commit()

    return {
        "message": "Datos de muestra creados exitosamente",
        "reps_created": len([r for r in reps if r.id]),
        "doctors_created": len([d for d in doctors if d.id]),
        "visits_created": visits_created
    }
