from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import KnowledgeBase, BusinessLine
from ..schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseOut

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("", response_model=List[KnowledgeBaseOut])
def get_all(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(KnowledgeBase).order_by(KnowledgeBase.category, KnowledgeBase.title)
    if category:
        query = query.filter(KnowledgeBase.category == category)
    items = query.all()
    result = []
    for item in items:
        out = KnowledgeBaseOut(
            id=item.id,
            title=item.title,
            category=item.category,
            content=item.content,
            business_line_id=item.business_line_id,
            business_line_name=item.business_line.name if item.business_line else None,
            is_active=item.is_active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        result.append(out)
    return result


@router.get("/categories")
def get_categories():
    return [
        {"value": "productos", "label": "Productos y Medicamentos"},
        {"value": "protocolos", "label": "Protocolos de Visita"},
        {"value": "faq", "label": "Preguntas Frecuentes"},
        {"value": "general", "label": "Información General"},
    ]


@router.post("", response_model=KnowledgeBaseOut)
def create(data: KnowledgeBaseCreate, db: Session = Depends(get_db)):
    item = KnowledgeBase(
        title=data.title,
        category=data.category,
        content=data.content,
        business_line_id=data.business_line_id,
        is_active=data.is_active if data.is_active is not None else True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return KnowledgeBaseOut(
        id=item.id,
        title=item.title,
        category=item.category,
        content=item.content,
        business_line_id=item.business_line_id,
        business_line_name=item.business_line.name if item.business_line else None,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.put("/{item_id}", response_model=KnowledgeBaseOut)
def update(item_id: int, data: KnowledgeBaseUpdate, db: Session = Depends(get_db)):
    item = db.query(KnowledgeBase).filter(KnowledgeBase.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return KnowledgeBaseOut(
        id=item.id,
        title=item.title,
        category=item.category,
        content=item.content,
        business_line_id=item.business_line_id,
        business_line_name=item.business_line.name if item.business_line else None,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/{item_id}")
def delete(item_id: int, db: Session = Depends(get_db)):
    item = db.query(KnowledgeBase).filter(KnowledgeBase.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    db.delete(item)
    db.commit()
    return {"message": "Eliminado exitosamente"}
