from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from ..models import UploadedImage

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("")
def list_images(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(UploadedImage).order_by(UploadedImage.created_at.desc())
    if category:
        query = query.filter(UploadedImage.category == category)
    images = query.all()
    return [{
        "id": img.id,
        "name": img.name,
        "description": img.description,
        "filename": img.filename,
        "category": img.category,
        "business_line_id": img.business_line_id,
        "business_line_name": img.business_line.name if img.business_line else None,
        "is_active": img.is_active,
        "url": f"/api/images/{img.id}/file",
        "created_at": img.created_at.isoformat() if img.created_at else None,
    } for img in images]


@router.get("/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db)):
    img = db.query(UploadedImage).filter(UploadedImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    return Response(content=img.data, media_type=img.content_type)


@router.post("")
def upload_image(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    category: str = Form("qr"),
    business_line_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml']
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Formato no soportado: {file.content_type}")

    data = file.file.read()
    if len(data) > 5 * 1024 * 1024:  # 5MB max
        raise HTTPException(status_code=400, detail="Archivo muy grande (max 5MB)")

    bl_id = int(business_line_id) if business_line_id and business_line_id.strip() else None

    img = UploadedImage(
        name=name,
        description=description,
        filename=file.filename or "image.png",
        content_type=file.content_type,
        data=data,
        category=category,
        business_line_id=bl_id,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return {
        "id": img.id,
        "name": img.name,
        "url": f"/api/images/{img.id}/file",
        "message": "Imagen subida exitosamente",
    }


@router.delete("/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(UploadedImage).filter(UploadedImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    db.delete(img)
    db.commit()
    return {"message": "Imagen eliminada"}
