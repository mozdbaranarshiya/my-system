import os
import re
from decimal import Decimal, InvalidOperation

from flask import abort
from flask_login import current_user
from sqlalchemy import and_, or_

from . import db
from .models import Announcement, GradeLock, StudentProfile, TeacherAssignment, User


NATIONAL_ID_RE = re.compile(r"^\d{10}$")


def valid_national_id(value):
    return bool(NATIONAL_ID_RE.fullmatch((value or "").strip()))


def parse_score(value):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        score = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("نمره باید عدد باشد.") from exc
    if score < 0 or score > 20:
        raise ValueError("نمره باید بین ۰ تا ۲۰ باشد.")
    return score.quantize(Decimal("0.01"))


def ensure_initial_admin():
    if User.query.filter_by(role="admin").first():
        return
    national_id = (os.getenv("ADMIN_NATIONAL_ID") or "").strip()
    full_name = (os.getenv("ADMIN_FULL_NAME") or "مدیر سامانه").strip()
    if not valid_national_id(national_id):
        return
    admin = User(national_id=national_id, username=national_id, full_name=full_name, role="admin")
    admin.set_password(national_id)
    db.session.add(admin)
    db.session.commit()


def require_role(*roles):
    if not current_user.is_authenticated or current_user.role not in roles:
        abort(403)


def teacher_has_assignment(user_id, classroom_id, subject_id):
    return TeacherAssignment.query.filter_by(
        teacher_id=user_id,
        classroom_id=classroom_id,
        subject_id=subject_id,
    ).first() is not None


def can_access_gradebook(user, classroom_id, subject_id):
    if user.role == "admin":
        return True
    return user.role == "teacher" and teacher_has_assignment(user.id, classroom_id, subject_id)


def is_component_locked(classroom_id, subject_id, component):
    return GradeLock.query.filter_by(
        classroom_id=classroom_id,
        subject_id=subject_id,
        component=component,
    ).first() is not None


def announcements_for_user(user):
    clauses = [Announcement.target_type == "all", Announcement.target_user_id == user.id]
    if user.role == "teacher":
        clauses.append(Announcement.target_type == "teachers")
    elif user.role == "student":
        clauses.append(Announcement.target_type == "students")
        if user.student_profile:
            clauses.append(
                and_(
                    Announcement.target_type == "class",
                    Announcement.target_classroom_id == user.student_profile.classroom_id,
                )
            )
    return Announcement.query.filter(or_(*clauses)).order_by(Announcement.created_at.desc()).all()


def students_in_classroom(classroom_id):
    return (
        User.query.join(StudentProfile)
        .filter(User.role == "student", StudentProfile.classroom_id == classroom_id)
        .order_by(User.full_name.asc())
        .all()
    )
