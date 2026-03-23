from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Any
import os
import json
import httpx
from dotenv import load_dotenv
load_dotenv()
from ..database import get_db
from ..models import Visit, Doctor, MedicalRep, KnowledgeBase
from ..schemas import AgentChatRequest, AgentChatResponse, AgentMessage

router = APIRouter(prefix="/api/agent", tags=["agent"])

SYSTEM_PROMPT = """Eres un asistente de IA para visitadores médicos farmacéuticos. Tu rol es ayudar a los visitadores médicos a:
- Gestionar su agenda de visitas
- Consultar información de sus médicos asignados
- Registrar visitas realizadas
- Obtener información sobre su cardex

Siempre responde en español. Sé profesional y conciso."""

TOOLS = [
    {
        "name": "get_my_visits",
        "description": "Obtiene las visitas del visitador médico. Puede filtrar por período: today (hoy), week (esta semana), upcoming (próximas), o all (todas).",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["today", "week", "upcoming", "all"],
                    "description": "Período de tiempo para filtrar visitas"
                }
            },
            "required": ["period"]
        }
    },
    {
        "name": "get_my_doctors",
        "description": "Obtiene la lista de médicos asignados al visitador.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Búsqueda opcional por nombre del médico"
                }
            }
        }
    },
    {
        "name": "schedule_visit",
        "description": "Programa una nueva visita a un médico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {
                    "type": "integer",
                    "description": "ID del médico a visitar"
                },
                "scheduled_date": {
                    "type": "string",
                    "description": "Fecha y hora de la visita en formato ISO 8601 (YYYY-MM-DDTHH:MM:SS)"
                },
                "notes": {
                    "type": "string",
                    "description": "Notas adicionales para la visita"
                }
            },
            "required": ["doctor_id", "scheduled_date"]
        }
    },
    {
        "name": "complete_visit",
        "description": "Marca una visita como completada y agrega notas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "visit_id": {
                    "type": "integer",
                    "description": "ID de la visita a completar"
                },
                "notes": {
                    "type": "string",
                    "description": "Notas sobre la visita realizada"
                }
            },
            "required": ["visit_id"]
        }
    },
    {
        "name": "get_doctor_info",
        "description": "Obtiene información detallada de un médico específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_id": {
                    "type": "integer",
                    "description": "ID del médico"
                }
            },
            "required": ["doctor_id"]
        }
    }
]


def execute_tool(tool_name: str, tool_input: dict, rep_id: int, db: Session) -> Any:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    if tool_name == "get_my_visits":
        period = tool_input.get("period", "today")
        query = db.query(Visit).filter(Visit.rep_id == rep_id)

        if period == "today":
            query = query.filter(
                Visit.scheduled_date >= today_start,
                Visit.scheduled_date < today_end
            )
        elif period == "week":
            week_end = today_start + timedelta(days=7)
            query = query.filter(
                Visit.scheduled_date >= today_start,
                Visit.scheduled_date < week_end
            )
        elif period == "upcoming":
            query = query.filter(
                Visit.scheduled_date >= today_start,
                Visit.status == "scheduled"
            ).limit(20)

        visits = query.order_by(Visit.scheduled_date.asc()).limit(50).all()
        result = []
        for v in visits:
            result.append({
                "visit_id": v.id,
                "doctor_name": v.doctor.name if v.doctor else "N/A",
                "doctor_specialty": v.doctor.specialty if v.doctor else None,
                "scheduled_date": v.scheduled_date.isoformat() if v.scheduled_date else None,
                "status": v.status,
                "notes": v.notes
            })
        return {"visits": result, "total": len(result)}

    elif tool_name == "get_my_doctors":
        search = tool_input.get("search", "")
        query = db.query(Doctor).filter(Doctor.rep_id == rep_id, Doctor.is_active == True)
        if search:
            query = query.filter(Doctor.name.ilike(f"%{search}%"))
        doctors = query.all()
        result = []
        for d in doctors:
            result.append({
                "doctor_id": d.id,
                "name": d.name,
                "specialty": d.specialty,
                "phone": d.phone,
                "address": d.address,
                "visit_frequency": d.visit_frequency,
                "prescribes_products": d.prescribes_products,
                "business_line": d.business_line.name if d.business_line else None
            })
        return {"doctors": result, "total": len(result)}

    elif tool_name == "schedule_visit":
        doctor_id = tool_input.get("doctor_id")
        scheduled_date_str = tool_input.get("scheduled_date")
        notes = tool_input.get("notes", "")

        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            return {"error": f"Médico con ID {doctor_id} no encontrado"}

        try:
            scheduled_date = datetime.fromisoformat(scheduled_date_str)
        except ValueError:
            return {"error": f"Formato de fecha inválido: {scheduled_date_str}"}

        visit = Visit(
            doctor_id=doctor_id,
            rep_id=rep_id,
            scheduled_date=scheduled_date,
            status="scheduled",
            notes=notes
        )
        db.add(visit)
        db.commit()
        db.refresh(visit)
        return {
            "success": True,
            "visit_id": visit.id,
            "message": f"Visita programada con {doctor.name} para {scheduled_date.strftime('%d/%m/%Y %H:%M')}"
        }

    elif tool_name == "complete_visit":
        visit_id = tool_input.get("visit_id")
        notes = tool_input.get("notes", "")

        visit = db.query(Visit).filter(Visit.id == visit_id, Visit.rep_id == rep_id).first()
        if not visit:
            return {"error": f"Visita con ID {visit_id} no encontrada"}

        visit.status = "completed"
        visit.actual_date = datetime.utcnow()
        if notes:
            visit.notes = notes
        db.commit()
        return {
            "success": True,
            "message": f"Visita marcada como completada",
            "visit_id": visit_id,
            "doctor_name": visit.doctor.name if visit.doctor else "N/A"
        }

    elif tool_name == "get_doctor_info":
        doctor_id = tool_input.get("doctor_id")
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if not doctor:
            return {"error": f"Médico con ID {doctor_id} no encontrado"}

        last_visit = db.query(Visit).filter(
            Visit.doctor_id == doctor_id,
            Visit.status == "completed"
        ).order_by(Visit.actual_date.desc()).first()

        next_visit = db.query(Visit).filter(
            Visit.doctor_id == doctor_id,
            Visit.status == "scheduled",
            Visit.scheduled_date >= datetime.utcnow()
        ).order_by(Visit.scheduled_date.asc()).first()

        return {
            "doctor_id": doctor.id,
            "name": doctor.name,
            "specialty": doctor.specialty,
            "address": doctor.address,
            "phone": doctor.phone,
            "email": doctor.email,
            "business_line": doctor.business_line.name if doctor.business_line else None,
            "prescribes_products": doctor.prescribes_products,
            "visit_frequency_days": doctor.visit_frequency,
            "notes": doctor.notes,
            "last_visit": last_visit.actual_date.isoformat() if last_visit and last_visit.actual_date else None,
            "next_visit": next_visit.scheduled_date.isoformat() if next_visit else None
        }

    return {"error": f"Herramienta desconocida: {tool_name}"}


@router.get("/check")
def check_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return {"status": "ok", "key_preview": key[:12] + "..."}
    all_keys = sorted(os.environ.keys())
    return {"status": "missing", "total_env_vars": len(all_keys), "all_keys": all_keys}

@router.post("/chat", response_model=AgentChatResponse)
def chat(request: AgentChatRequest, db: Session = Depends(get_db)):
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY no configurada")

    rep = db.query(MedicalRep).filter(MedicalRep.id == request.rep_id).first()
    if not rep:
        raise HTTPException(status_code=404, detail="Visitador no encontrado")

    try:
        messages = []
        for msg in request.conversation_history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": request.message})

        # Load knowledge base
        kb_entries = db.query(KnowledgeBase).filter(KnowledgeBase.is_active == True).all()
        kb_text = ""
        if kb_entries:
            kb_text = "\n\n--- BASE DE CONOCIMIENTO ---\nUsa esta información para responder preguntas sobre productos, protocolos y procedimientos:\n\n"
            for entry in kb_entries:
                bl_name = entry.business_line.name if entry.business_line else "General"
                kb_text += f"[{entry.category.upper()} - {bl_name}] {entry.title}:\n{entry.content}\n\n"

        system_with_context = f"{SYSTEM_PROMPT}\n\nContexto actual:\n- Visitador: {rep.name}\n- ID: {rep.id}\n- Fecha actual: {datetime.utcnow().strftime('%d/%m/%Y %H:%M')}{kb_text}"

        # Tool-calling loop
        final_response = ""
        max_iterations = 5
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Direct HTTP call to Anthropic API
            with httpx.Client(timeout=60.0) as http_client:
                api_response = http_client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 2048,
                        "system": system_with_context,
                        "tools": TOOLS,
                        "messages": messages,
                    }
                )

            if api_response.status_code != 200:
                raise Exception(f"Anthropic API error {api_response.status_code}: {api_response.text}")

            response_data = api_response.json()
            stop_reason = response_data.get("stop_reason", "")
            content = response_data.get("content", [])

            # Check stop reason
            if stop_reason == "end_turn":
                for block in content:
                    if block.get("type") == "text":
                        final_response = block.get("text", "")
                break

            elif stop_reason == "tool_use":
                tool_results = []

                for block in content:
                    if block.get("type") == "tool_use":
                        tool_result = execute_tool(block["name"], block["input"], request.rep_id, db)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": json.dumps(tool_result, ensure_ascii=False, default=str)
                        })

                # Add assistant message with tool use
                messages.append({
                    "role": "assistant",
                    "content": content
                })

                # Add tool results
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
            else:
                final_response = "Lo siento, ocurrió un error inesperado."
                break

        if not final_response:
            final_response = "Lo siento, no pude procesar tu solicitud."

    except Exception as e:
        import traceback
        print(f"ERROR in agent chat: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error del agente: {str(e)}")

    # Build updated conversation history
    updated_history = list(request.conversation_history)
    updated_history.append(AgentMessage(role="user", content=request.message))
    updated_history.append(AgentMessage(role="assistant", content=final_response))

    return AgentChatResponse(
        response=final_response,
        conversation_history=updated_history
    )
