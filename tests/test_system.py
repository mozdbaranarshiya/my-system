import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret")

from school_system import create_app, db
from school_system.models import Classroom, GradeLevel, GradeLock, Objection, Score, StudentProfile, Subject, TeacherAssignment, User


@pytest.fixture()
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
    })
    with app.app_context():
        db.create_all()

        grade = GradeLevel(name="هفتم", sort_order=7)
        db.session.add(grade)
        db.session.flush()
        classroom = Classroom(name="الف", grade_level_id=grade.id)
        subject = Subject(name="ریاضی", grade_level_id=grade.id)
        db.session.add_all([classroom, subject])
        db.session.flush()

        admin = User(national_id="1111111111", username="1111111111", full_name="مدیر", role="admin")
        teacher = User(national_id="2222222222", username="2222222222", full_name="معلم", role="teacher")
        other_teacher = User(national_id="3333333333", username="3333333333", full_name="معلم دوم", role="teacher")
        student = User(national_id="4444444444", username="4444444444", full_name="دانش‌آموز", role="student")
        for u in (admin, teacher, other_teacher, student):
            u.set_password(u.national_id)
        db.session.add_all([admin, teacher, other_teacher, student])
        db.session.flush()
        db.session.add(StudentProfile(user_id=student.id, classroom_id=classroom.id))
        db.session.add(TeacherAssignment(teacher_id=teacher.id, classroom_id=classroom.id, subject_id=subject.id))
        db.session.commit()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username, password=None):
    return client.post("/login", data={"username": username, "password": password or username}, follow_redirects=True)


def ids(app):
    with app.app_context():
        return {
            "classroom": Classroom.query.one().id,
            "subject": Subject.query.one().id,
            "student": User.query.filter_by(role="student").one().id,
            "teacher": User.query.filter_by(username="2222222222").one().id,
        }


def test_course_score_is_average(app):
    data = ids(app)
    with app.app_context():
        score = Score(student_id=data["student"], classroom_id=data["classroom"], subject_id=data["subject"], formative=18, final=16)
        assert score.course_score == 17.0


def test_teacher_cannot_access_unassigned_gradebook(app, client):
    data = ids(app)
    login(client, "3333333333")
    response = client.get(f'/gradebook/{data["classroom"]}/{data["subject"]}')
    assert response.status_code == 403


def test_teacher_finalize_saves_then_locks(app, client):
    data = ids(app)
    login(client, "2222222222")
    response = client.post(
        f'/gradebook/{data["classroom"]}/{data["subject"]}',
        data={"action": "finalize_formative", f'formative_{data["student"]}': "17.5"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        score = Score.query.one()
        assert float(score.formative) == 17.5
        assert GradeLock.query.filter_by(classroom_id=data["classroom"], subject_id=data["subject"], component="formative").one()


def test_locked_component_cannot_be_changed_by_teacher(app, client):
    data = ids(app)
    with app.app_context():
        db.session.add(Score(student_id=data["student"], classroom_id=data["classroom"], subject_id=data["subject"], formative=12, final=10))
        db.session.add(GradeLock(classroom_id=data["classroom"], subject_id=data["subject"], component="formative", locked_by_id=data["teacher"]))
        db.session.commit()
    login(client, "2222222222")
    client.post(
        f'/gradebook/{data["classroom"]}/{data["subject"]}',
        data={"action": "save", f'formative_{data["student"]}': "19", f'final_{data["student"]}': "15"},
        follow_redirects=True,
    )
    with app.app_context():
        score = Score.query.one()
        assert float(score.formative) == 12.0
        assert float(score.final) == 15.0


def test_teacher_cannot_use_admin_unlock_action(app, client):
    data = ids(app)
    login(client, "2222222222")
    response = client.post(f'/gradebook/{data["classroom"]}/{data["subject"]}', data={"action": "unlock_formative"})
    assert response.status_code == 403


def test_approved_objection_changes_score(app, client):
    data = ids(app)
    with app.app_context():
        score = Score(student_id=data["student"], classroom_id=data["classroom"], subject_id=data["subject"], formative=10, final=14)
        db.session.add(score)
        db.session.flush()
        objection = Objection(student_id=data["student"], score_id=score.id, component="formative", reason="نمره برگه ۱۸ بوده است")
        db.session.add(objection)
        db.session.commit()
        objection_id = objection.id
    login(client, "2222222222")
    client.post(f"/objections/{objection_id}/resolve", data={"decision": "approve", "new_score": "18", "response": "بررسی شد"}, follow_redirects=True)
    with app.app_context():
        objection = db.session.get(Objection, objection_id)
        assert objection.status == "approved"
        assert float(objection.score.formative) == 18.0
        assert float(objection.previous_score) == 10.0


def test_reject_objection_requires_reason(app, client):
    data = ids(app)
    with app.app_context():
        score = Score(student_id=data["student"], classroom_id=data["classroom"], subject_id=data["subject"], formative=10)
        db.session.add(score)
        db.session.flush()
        objection = Objection(student_id=data["student"], score_id=score.id, component="formative", reason="اعتراض")
        db.session.add(objection)
        db.session.commit()
        objection_id = objection.id
    login(client, "2222222222")
    client.post(f"/objections/{objection_id}/resolve", data={"decision": "reject", "response": ""}, follow_redirects=True)
    with app.app_context():
        assert db.session.get(Objection, objection_id).status == "pending"
