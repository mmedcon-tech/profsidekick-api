import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database.models import Student


def create_student(db: Session, display_name: str, created_by_user_id) -> Student:
    seq_val = db.execute(text("SELECT nextval('student_code_seq')")).scalar()
    student_code = "STU-" + str(seq_val).zfill(3)
    student = Student(
        id=uuid.uuid4(),
        student_code=student_code,
        display_name=display_name,
        created_by=created_by_user_id,
        created_at=datetime.utcnow(),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def get_student_by_code(db: Session, code: str) -> Optional[Student]:
    return db.query(Student).filter(Student.student_code == code).first()


def get_student_by_id(db: Session, student_id) -> Optional[Student]:
    return db.query(Student).filter(Student.id == student_id).first()


def list_students(db: Session, created_by=None) -> list:
    query = db.query(Student)
    if created_by is not None:
        query = query.filter(Student.created_by == created_by)
    return query.order_by(Student.created_at.asc()).all()
