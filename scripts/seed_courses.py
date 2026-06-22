import os
import sys
import uuid
import bcrypt
import argparse
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def seed(reset=False):
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        print("DATABASE_URL not found in environment.")
        return

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    
    from app.database.models import (
        User, Course, CourseStudent, 
        Program, ProgramMembership, ProgramCourse, ProgramAvatar,
        AvatarTemplate, Avatar
    )

    db = SessionLocal()
    try:
        if reset:
            print("Resetting seed data...")
            # Delete in reverse dependency order
            db.query(ProgramMembership).delete()
            db.query(ProgramCourse).delete()
            db.query(ProgramAvatar).delete()
            db.query(CourseStudent).delete()
            db.query(Course).delete()
            db.query(Program).delete()
            db.query(Avatar).delete()
            db.query(AvatarTemplate).delete()
            db.commit()
            print("Seed data cleared.")

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

        # 3. Create Default Program
        program_slug = "moi-training"
        program = db.query(Program).filter(Program.slug == program_slug).first()
        if not program:
            program = Program(
                id=uuid.uuid4(),
                publisher_id=publisher.id,
                name="Ministry of Interior Training",
                slug=program_slug,
                description="Official training portal for the Ministry of Interior.",
                theme_config={
                    "brandName": "MOI Training",
                    "primaryColor": "#0a1e13",
                    "secondaryColor": "#d4af37",
                    "accentColor": "#ffffff",
                    "fontFamily": "Inter, sans-serif"
                },
                is_active=True,
                is_public=False
            )
            db.add(program)
            db.flush()
            print(f"Created program: {program.name}")

        # 4. Create Default Avatar Template and Avatar
        template = db.query(AvatarTemplate).filter(AvatarTemplate.name == "Default Instructor").first()
        if not template:
            template = AvatarTemplate(
                id=uuid.uuid4(),
                created_by=publisher.id,
                name="Default Instructor",
                description="Standard instructional avatar",
                is_active=True
            )
            db.add(template)
            db.flush()
            print(f"Created AvatarTemplate: {template.name}")
            
        avatar = db.query(Avatar).filter(Avatar.name == "MOI Avatar").first()
        if not avatar:
            avatar = Avatar(
                id=uuid.uuid4(),
                template_id=template.id,
                publisher_id=publisher.id,
                name="MOI Avatar",
                description="Default instructor for MOI courses",
                is_published=True
            )
            db.add(avatar)
            db.flush()
            print(f"Created Avatar: {avatar.name}")
            
            # Link Avatar to Program
            prog_avatar = ProgramAvatar(
                id=uuid.uuid4(),
                program_id=program.id,
                avatar_id=avatar.id
            )
            db.add(prog_avatar)
            db.flush()

        # 5. MOI Courses data
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
                
                # Link Course to Program
                prog_course = ProgramCourse(
                    id=uuid.uuid4(),
                    program_id=program.id,
                    course_id=course.id
                )
                db.add(prog_course)
                
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
        
        # 6. Enroll Subscriber in Program
        prog_membership = db.query(ProgramMembership).filter(
            ProgramMembership.program_id == program.id,
            ProgramMembership.user_id == subscriber.id
        ).first()
        
        if not prog_membership:
            prog_membership = ProgramMembership(
                id=uuid.uuid4(),
                program_id=program.id,
                user_id=subscriber.id
            )
            db.add(prog_membership)
            
            # Set current program
            subscriber.current_program_id = program.id
            
        db.commit()
        print("\nSuccessfully seeded V2 MOI objects: Program, Avatar, Courses, and Memberships.")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed database for MyOS V2.")
    parser.add_argument("--reset", action="store_true", help="Clear existing seed data before inserting.")
    args = parser.parse_args()
    seed(reset=args.reset)
