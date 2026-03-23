from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# Business Line schemas
class BusinessLineBase(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = "#3B82F6"


class BusinessLineCreate(BusinessLineBase):
    pass


class BusinessLineUpdate(BusinessLineBase):
    name: Optional[str] = None


class BusinessLineOut(BusinessLineBase):
    id: int
    created_at: Optional[datetime] = None
    doctor_count: Optional[int] = 0

    class Config:
        from_attributes = True


# Medical Rep schemas
class MedicalRepBase(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    territory: Optional[str] = None
    zone: Optional[str] = None
    is_active: Optional[bool] = True


class MedicalRepCreate(MedicalRepBase):
    pass


class MedicalRepUpdate(MedicalRepBase):
    name: Optional[str] = None
    email: Optional[str] = None


class MedicalRepOut(MedicalRepBase):
    id: int
    created_at: Optional[datetime] = None
    doctor_count: Optional[int] = 0

    class Config:
        from_attributes = True


# Doctor schemas
class DoctorBase(BaseModel):
    name: str
    rut: Optional[str] = None
    medical_center: Optional[str] = None
    specialty: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    business_line_id: Optional[int] = None
    rep_id: Optional[int] = None
    prescribes_products: Optional[str] = None
    visit_frequency: Optional[int] = 30
    is_active: Optional[bool] = True


class DoctorCreate(DoctorBase):
    pass


class DoctorUpdate(DoctorBase):
    name: Optional[str] = None


class DoctorOut(DoctorBase):
    id: int
    created_at: Optional[datetime] = None
    business_line_name: Optional[str] = None
    rep_name: Optional[str] = None
    last_visit_date: Optional[datetime] = None
    visits_count: Optional[int] = 0
    has_sales: Optional[bool] = False

    class Config:
        from_attributes = True


class AssignRepRequest(BaseModel):
    rep_id: int


# Visit schemas
class VisitBase(BaseModel):
    doctor_id: int
    rep_id: int
    scheduled_date: datetime
    status: Optional[str] = "scheduled"
    notes: Optional[str] = None


class VisitCreate(VisitBase):
    pass


class VisitUpdate(BaseModel):
    status: Optional[str] = None
    actual_date: Optional[datetime] = None
    notes: Optional[str] = None
    scheduled_date: Optional[datetime] = None


class VisitOut(VisitBase):
    id: int
    actual_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    doctor_name: Optional[str] = None
    rep_name: Optional[str] = None
    doctor_specialty: Optional[str] = None

    class Config:
        from_attributes = True


class GenerateVisitsRequest(BaseModel):
    rep_id: Optional[int] = None
    months_ahead: Optional[int] = 6


# Sales schemas
class SaleOut(BaseModel):
    id: int
    doctor_id: Optional[int] = None
    doctor_name_raw: Optional[str] = None
    product: Optional[str] = None
    amount: Optional[float] = None
    sale_date: Optional[datetime] = None
    upload_id: Optional[int] = None
    created_at: Optional[datetime] = None
    doctor_name: Optional[str] = None

    class Config:
        from_attributes = True


class SalesSummaryItem(BaseModel):
    doctor_id: Optional[int] = None
    doctor_name: str
    total_sales: float
    sales_count: int
    visits_count: int
    has_visits: bool


# Dashboard schemas
class DashboardStats(BaseModel):
    total_doctors: int
    active_reps: int
    visits_today: int
    visits_this_week: int
    total_visits: int
    completed_visits: int
    missed_visits: int


class RepStats(BaseModel):
    rep_id: int
    rep_name: str
    doctor_count: int
    visits_today: int
    visits_this_week: int
    completed_this_month: int
    missed_this_month: int


# AI Agent schemas
class AgentMessage(BaseModel):
    role: str
    content: str


class AgentChatRequest(BaseModel):
    message: str
    rep_id: int
    conversation_history: Optional[List[AgentMessage]] = []


class AgentChatResponse(BaseModel):
    response: str
    conversation_history: List[AgentMessage]


# Knowledge Base schemas
class KnowledgeBaseCreate(BaseModel):
    title: str
    category: str
    content: str
    business_line_id: Optional[int] = None
    is_active: Optional[bool] = True


class KnowledgeBaseUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    business_line_id: Optional[int] = None
    is_active: Optional[bool] = None


class KnowledgeBaseOut(BaseModel):
    id: int
    title: str
    category: str
    content: str
    business_line_id: Optional[int] = None
    business_line_name: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
