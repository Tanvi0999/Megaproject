import random
from faker import Faker
from app.database import SessionLocal, engine, Base
from app.models import (
    Student, Skill, Career, Recommendation, RecommendedCareer
)

fake = Faker()

def seed_database():
    # Ensure all tables are created based on the updated models
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("Seeding Skills...")
        skill_names = ["Python", "Java", "Spring Boot", "React", "Docker", "PostgreSQL", "Machine Learning", "Data Structures", "FastAPI", "Kubernetes"]
        db_skills = []
        for name in skill_names:
            skill = Skill(skill_name=name, category="Technical")
            db.add(skill)
            db_skills.append(skill)
        db.commit()

        print("Seeding Careers...")
        career_names = ["Software Engineer", "Data Scientist", "DevOps Engineer", "Frontend Developer", "Backend Developer"]
        db_careers = []
        for name in career_names:
            career = Career(
                career_name=name,
                industry="Technology",
                minimum_cgpa=round(random.uniform(6.5, 8.0), 1)
            )
            db.add(career)
            db_careers.append(career)
        db.commit()

        print("Seeding Students and Recommendations...")
        for _ in range(15): # Generate 15 mock students
            student_skills = random.sample(skill_names, 4)
            student = Student(
                student_name=fake.name(),
                email=fake.unique.email(),
                roll_number=fake.unique.bothify(text='CSE26###'),
                branch="Computer Science Engineering",
                academic_year=2026,
                cgpa=round(random.uniform(6.5, 9.8), 2),
                skills=student_skills,
                interests=["Web Development", "AI", "Cloud Computing"]
            )
            db.add(student)
            db.commit()
            db.refresh(student)

            # Generate a mock ML recommendation for each student
            rec = Recommendation(
                student_id=student.student_id,
                model_name="career-rf-v1",
                status="completed",
                input_snapshot={"cgpa": student.cgpa, "skills": student.skills}
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)

            # Assign 2 recommended careers to this recommendation
            sampled_careers = random.sample(db_careers, 2)
            for rank, car in enumerate(sampled_careers, start=1):
                rec_car = RecommendedCareer(
                    recommendation_id=rec.recommendation_id,
                    career_id=car.career_id,
                    career_name=car.career_name,
                    rank=rank,
                    match_score=round(random.uniform(75.0, 99.0), 2),
                    matched_skills=random.sample(student_skills, 2)
                )
                db.add(rec_car)

        db.commit()
        print("Database successfully seeded with students, skills, and recommendations!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()