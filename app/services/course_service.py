from typing import List
from sqlalchemy.orm import Session
from datetime import datetime
from app.database.models import Course, User, CourseStudent, Session as SessionModel
from fastapi import HTTPException
from uuid import UUID
from app.schemas.schemas import CourseDetails, CourseCreate, CourseUpdate, CourseStudent as CourseStudentSchema, CourseSessionSummary
import uuid
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class CourseService:
    """Service for managing courses"""
    
    def __init__(self):
        pass
    
    def generate_course_id(self) -> str:
        """Generate a unique course ID"""
        return f"course_{uuid.uuid4().hex[:12]}"

    async def create_course(self, db: Session, course_data: CourseCreate) -> CourseDetails:
        if course_data.user_id is not None:
            user = db.query(User).filter(User.id == course_data.user_id).first()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            if user.role != "publisher":
                raise HTTPException(status_code=403, detail="User is not a publisher")
        else:
            raise HTTPException(status_code=400, detail="User ID is required")

        course_id = self.generate_course_id()
        course = Course(
            course_id=course_id,
            user_id=course_data.user_id,
            name=course_data.name,
            code=course_data.code,
            section=course_data.section,
            description=course_data.description,
            department=course_data.department,
            semester=course_data.semester,
            year=course_data.year,
            syllabus_details=course_data.syllabus_details,
            is_active=course_data.is_active,
            is_deleted=course_data.is_deleted,
            is_public=course_data.is_public,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(course)
        db.commit()
        db.refresh(course)
        return CourseDetails(**course.__dict__)

    async def get_courses(self, db: Session, user_id: UUID) -> List[CourseDetails]:
        if user_id is None:
            return []
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        if user.role == "publisher":
            # Publishers see only their own courses — unchanged
            courses = db.query(Course).filter(Course.user_id == user.id).all()
            for course in courses:
                course.owner_name = f"{user.first_name} {user.last_name}"
                course.enrollment_count = len(course.students)

        elif user.role in ("admin", "subscriber"):
            # Admins and subscribers see every course on the platform
            courses = db.query(Course).all()
            for course in courses:
                owner = course.user
                course.owner_name = (
                    f"{owner.first_name} {owner.last_name}" if owner else "Unknown"
                )
                course.enrollment_count = len(course.students)

        else:
            raise HTTPException(status_code=403, detail="Unrecognised role")

        return [CourseDetails(**course.__dict__) for course in courses]
    
    async def get_course(self, db: Session, course_id: str, user_id: UUID) -> CourseDetails:
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        # if course.user_id != user_id:
        #     raise HTTPException(status_code=403, detail="User is not the owner of the course")
        return CourseDetails(**course.__dict__)
        
    async def update_course(self, db: Session, course_id: str, course_data: CourseUpdate) -> CourseDetails:
        if course_data.user_id is not None:
            user = db.query(User).filter(User.id == course_data.user_id).first()
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            if user.role != "publisher":
                raise HTTPException(status_code=403, detail="User is not a publisher")
        else:
            raise HTTPException(status_code=400, detail="User ID is required")

        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.user_id != user.id:
            raise HTTPException(status_code=403, detail="User is not the owner of the course")

        course.name = course_data.name
        course.description = course_data.description
        course.department = course_data.department
        course.semester = course_data.semester
        course.year = course_data.year
        course.syllabus_details = course_data.syllabus_details
        course.is_active = course_data.is_active
        course.is_deleted = course_data.is_deleted
        course.is_public = course_data.is_public
        course.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(course)
        return CourseDetails(**course.__dict__)
    
    async def delete_course(self, db: Session, course_id: str, user_id: UUID) -> CourseDetails:
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.user_id != user_id:
            raise HTTPException(status_code=403, detail="User is not the owner of the course")
        db.delete(course)
        db.commit()
        return CourseDetails(**course.__dict__)
    
    async def enroll_course(self, db: Session, course_id: str, user_id: UUID, student_email: str) -> CourseDetails:
        # Check if the user is a professor and owns the course
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != "publisher":
            raise HTTPException(status_code=403, detail="Only publishers can enroll subscribers")
        
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            logger.error(f"❌ Course not found: {course_id}")
            raise HTTPException(status_code=404, detail="Course not found")
        if course.user_id != user_id:
            logger.error(f"❌ User is not the owner of the course: {course_id}")
            raise HTTPException(status_code=403, detail="You can only enroll students in your own courses")
            
        student = db.query(User).filter(User.email == student_email).first()
        if student is None:
            logger.error(f"❌ Student not found: {student_email}")
            raise HTTPException(status_code=404, detail="Student not found")
        if student.role != "subscriber":
            logger.error(f"❌ Student is not a student: {student_email}")
            raise HTTPException(status_code=400, detail="Can only enroll users with subscriber role")
        
        # Check if student is already enrolled
        existing_enrollment = db.query(CourseStudent).filter(
            CourseStudent.course_id == course.id,
            CourseStudent.user_id == student.id
        ).first()
        if existing_enrollment:
            raise HTTPException(status_code=400, detail="Student is already enrolled in this course")
        
        # Create enrollment record
        enrollment = CourseStudent(
            course_id=course.id,
            user_id=student.id,
            enrollment_date=datetime.utcnow()
        )
        db.add(enrollment)
        db.commit()
        db.refresh(course)
        return CourseDetails(**course.__dict__)
    
    async def get_course_students(self, db: Session, course_id: str, user_id: UUID) -> List[CourseStudentSchema]:
        # Check if the user is a professor and owns the course
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != "publisher":
            raise HTTPException(status_code=403, detail="Only publishers can view course students")
            
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.user_id != user_id:
            raise HTTPException(status_code=403, detail="You can only view students in your own courses")
        
        # Get enrolled students with enrollment details
        enrollments = db.query(CourseStudent, User).join(
            User, CourseStudent.user_id == User.id
        ).filter(CourseStudent.course_id == course.id).all()
        
        students = []
        for enrollment, student in enrollments:
            students.append(CourseStudentSchema(
                id=student.id,
                username=student.username,
                email=student.email,
                firstName=student.first_name,
                lastName=student.last_name,
                enrollment_date=enrollment.enrollment_date
            ))
        
        return students
    
    async def remove_student_from_course(self, db: Session, course_id: str, student_id: str, user_id: UUID):
        # Check if the user is a professor and owns the course
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user.role != "publisher":
            raise HTTPException(status_code=403, detail="Only publishers can remove subscribers")
            
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.user_id != user_id:
            raise HTTPException(status_code=403, detail="You can only remove students from your own courses")
        
        # Find and remove enrollment
        enrollment = db.query(CourseStudent).filter(
            CourseStudent.course_id == course.id,
            CourseStudent.user_id == UUID(student_id)
        ).first()
        if enrollment is None:
            raise HTTPException(status_code=404, detail="Student not found in this course")
        
        db.delete(enrollment)
        db.commit()
    
    async def get_course_sessions(self, db: Session, course_id: str, user_id: UUID) -> List[CourseSessionSummary]:
        # Check if the user has access to the course
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
            
        course = db.query(Course).filter(Course.course_id == course_id).first()
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        
        # Check access rights
        if user.role == "publisher" and course.user_id != user_id:
            raise HTTPException(status_code=403, detail="You can only view sessions in your own courses")
        elif user.role == "subscriber":
            # Subscribers who are not enrolled see an empty session list — not an error
            enrollment = db.query(CourseStudent).filter(
                CourseStudent.course_id == course.id,
                CourseStudent.user_id == user_id
            ).first()
            if not enrollment:
                return []
        # admin: no restriction — falls through and returns all sessions
        
        # Get sessions for the course
        sessions = db.query(SessionModel).filter(SessionModel.course_id == course.id).all()
        
        session_summaries = []
        for session in sessions:
            session_summaries.append(CourseSessionSummary(
                sessionId=session.session_id,
                session_number=session.session_number,
                session_date=session.session_date,
                class_name=session.class_name,
                description=session.description,
                duration=session.duration,
                created_at=session.created_at,
                updated_at=session.updated_at
            ))
        
        return session_summaries