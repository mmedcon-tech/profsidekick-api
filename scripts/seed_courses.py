import os
import uuid
import bcrypt
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure we import models after env setup or inside the function
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def seed():
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        print("DATABASE_URL not found in environment.")
        return

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    
    from app.database.models import User, Course, CourseStudent

    db = SessionLocal()
    try:
        # 1. Create an instructor / publisher
        pub_email = "instructor@profsidekick.com"
        publisher = db.query(User).filter(User.email == pub_email).first()
        if not publisher:
            publisher = User(
                id=uuid.uuid4(),
                username="instructor",
                email=pub_email,
                password_hash=hash_password("12345678"),
                first_name="MOI",
                last_name="Instructor",
                role="publisher",
                email_verified=True,
                is_approved=True,
            )
            db.add(publisher)
            db.flush()
            print(f"Created instructor: {pub_email}")

        # 2. Create a default subscriber (Rashid Al Mansoori)
        sub_email = "subscriber@profsidekick.com"
        subscriber = db.query(User).filter(User.email == sub_email).first()
        if not subscriber:
            subscriber = User(
                id=uuid.uuid4(),
                username="subscriber",
                email=sub_email,
                password_hash=hash_password("12345678"),
                first_name="Rashid",
                last_name="Al Mansoori",
                role="subscriber",
                email_verified=True,
                is_approved=True,
            )
            db.add(subscriber)
            db.flush()
            print(f"Created subscriber: {sub_email}")

        # 3. MOI Courses data
        courses_data = [
            {
                "name": "Basic Level Leadership",
                "description": "Develop scientific research, internal security operations and leadership skills for officers eligible for promotion.\n\nDuration: 8 weeks\nLocation: Officers Training Institute — Police College, Abu Dhabi",
                "department": "Rehabilitation & Promotion",
            },
            {
                "name": "AI Governance & Transformation",
                "description": "Understand responsible AI adoption across government, data privacy and the UAE AI strategy.\n\nDuration: 4 weeks\nLocation: Digital Learning — Online",
                "department": "AI Literacy",
            },
            {
                "name": "Occupational Health & Safety",
                "description": "Fundamental principles of occupational safety, planning and local & international standards.\n\nDuration: 4 weeks\nLocation: Officers Training Institute — Police College, Abu Dhabi",
                "department": "Occupational Health & Safety",
            },
            {
                "name": "Dealing with Prisoners & Detainees",
                "description": "Concepts of security and safety, handling detainees, and safety standards inside correctional facilities.\n\nDuration: 1 weeks\nLocation: Correctional Establishments Training Institute",
                "department": "Correctional Establishments",
            },
            {
                "name": "English Language (Intermediate)",
                "description": "Police terminology, sentence construction, and report writing in English for routine policing.\n\nDuration: 8 weeks\nLocation: Federal Police School — Sharjah",
                "department": "Foreign Languages",
            },
            {
                "name": "Basic Search & Rescue",
                "description": "VTOL craft safety, flight navigator duties, hoist rescue operations and air rescue practice.\n\nDuration: 8 weeks\nLocation: Air Wing — Sharjah",
                "department": "Air Wing",
            },
            # Added a couple more for good measure
            {
                "name": "Cybercrime Investigation Basics",
                "description": "Fundamentals of digital forensics, network security, and tracing digital footprints in cybercrime cases.\n\nDuration: 6 weeks\nLocation: Digital Learning — Online",
                "department": "Cyber Security",
            },
            {
                "name": "Crisis Management & Negotiation",
                "description": "Techniques for managing hostage situations, public disorder, and strategic negotiation tactics.\n\nDuration: 4 weeks\nLocation: Officers Training Institute — Police College, Abu Dhabi",
                "department": "Special Operations",
            }
        ]

        print("Seeding MOI courses...")
        for cdata in courses_data:
            course = db.query(Course).filter(Course.name == cdata["name"]).first()
            if not course:
                course_id_str = f"course_{uuid.uuid4().hex[:12]}"
                course = Course(
                    id=uuid.uuid4(),
                    course_id=course_id_str,
                    user_id=publisher.id,
                    name=cdata["name"],
                    description=cdata["description"],
                    department=cdata["department"],
                    is_active=True,
                    is_public=False,
                )
                db.add(course)
                db.flush()
                print(f"Created course: {course.name}")
                
                # Enroll the subscriber in the course
                enrollment = CourseStudent(
                    id=uuid.uuid4(),
                    course_id=course.id,
                    user_id=subscriber.id,
                    enrollment_date=datetime.utcnow()
                )
                db.add(enrollment)
            else:
                print(f"Course already exists: {course.name}")
        
        db.commit()
        print("\nSuccessfully seeded MOI courses and enrolled the default subscriber.")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
