from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text, LargeBinary
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class BusinessLine(Base):
    __tablename__ = "business_lines"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(20), default="#3B82F6")
    created_at = Column(DateTime, server_default=func.now())

    doctors = relationship("Doctor", back_populates="business_line")


class MedicalRep(Base):
    __tablename__ = "medical_reps"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    phone = Column(String(20), nullable=True)
    territory = Column(String(100), nullable=True)
    zone = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)

    doctors = relationship("Doctor", back_populates="rep")
    visits = relationship("Visit", back_populates="rep")


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    rut = Column(String(20), nullable=True, index=True)
    medical_center = Column(String(200), nullable=True)
    specialty = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(150), nullable=True)
    notes = Column(Text, nullable=True)
    business_line_id = Column(Integer, ForeignKey("business_lines.id"), nullable=True)
    rep_id = Column(Integer, ForeignKey("medical_reps.id"), nullable=True)
    prescribes_products = Column(Text, nullable=True)
    visit_frequency = Column(Integer, default=30)
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)

    business_line = relationship("BusinessLine", back_populates="doctors")
    rep = relationship("MedicalRep", back_populates="doctors")
    visits = relationship("Visit", back_populates="doctor")
    sales = relationship("Sale", back_populates="doctor")


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    rep_id = Column(Integer, ForeignKey("medical_reps.id"), nullable=False)
    scheduled_date = Column(DateTime, nullable=False)
    actual_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="scheduled")  # scheduled, completed, missed, cancelled
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    doctor = relationship("Doctor", back_populates="visits")
    rep = relationship("MedicalRep", back_populates="visits")


class SalesUpload(Base):
    __tablename__ = "sales_uploads"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    upload_date = Column(DateTime, server_default=func.now())
    rows_processed = Column(Integer, default=0)

    sales = relationship("Sale", back_populates="upload")


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=True)
    product = Column(String(200), nullable=True)
    category = Column(String(100), nullable=True)
    quantity = Column(Integer, default=1)
    amount = Column(Float, default=0.0)
    sale_date = Column(DateTime, nullable=True)
    upload_id = Column(Integer, ForeignKey("sales_uploads.id"), nullable=True)
    doctor_name_raw = Column(String(200), nullable=True)
    doctor_rut_raw = Column(String(20), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    doctor = relationship("Doctor", back_populates="sales")
    upload = relationship("SalesUpload", back_populates="sales")


class CardexUpload(Base):
    __tablename__ = "cardex_uploads"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    upload_date = Column(DateTime, server_default=func.now())
    rows_processed = Column(Integer, default=0)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)  # productos, protocolos, faq, general
    content = Column(Text, nullable=False)
    business_line_id = Column(Integer, ForeignKey("business_lines.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    business_line = relationship("BusinessLine")


class UploadedImage(Base):
    __tablename__ = "uploaded_images"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False)
    data = Column(LargeBinary, nullable=False)
    category = Column(String(100), default="qr")  # qr, product, general
    business_line_id = Column(Integer, ForeignKey("business_lines.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    business_line = relationship("BusinessLine")
