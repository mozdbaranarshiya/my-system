from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    national_id = db.Column(db.String(10), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)  # admin, teacher, student
    is_active_flag = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    student_profile = db.relationship("StudentProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")

    @property
    def is_active(self):
        return self.is_active_flag

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class GradeLevel(db.Model):
    __tablename__ = "grade_levels"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    classrooms = db.relationship("Classroom", back_populates="grade_level")
    subjects = db.relationship("Subject", back_populates="grade_level")


class Classroom(db.Model):
    __tablename__ = "classrooms"
    __table_args__ = (db.UniqueConstraint("grade_level_id", "name", name="uq_class_grade_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    grade_level_id = db.Column(db.Integer, db.ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    representative_student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    grade_level = db.relationship("GradeLevel", back_populates="classrooms")
    students = db.relationship("StudentProfile", back_populates="classroom")
    representative = db.relationship("User", foreign_keys=[representative_student_id])


class StudentProfile(db.Model):
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="RESTRICT"), nullable=False, index=True)

    user = db.relationship("User", back_populates="student_profile")
    classroom = db.relationship("Classroom", back_populates="students")


class Subject(db.Model):
    __tablename__ = "subjects"
    __table_args__ = (db.UniqueConstraint("grade_level_id", "name", name="uq_subject_grade_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    grade_level_id = db.Column(db.Integer, db.ForeignKey("grade_levels.id", ondelete="RESTRICT"), nullable=False, index=True)

    grade_level = db.relationship("GradeLevel", back_populates="subjects")


class TeacherAssignment(db.Model):
    __tablename__ = "teacher_assignments"
    __table_args__ = (db.UniqueConstraint("teacher_id", "classroom_id", "subject_id", name="uq_teacher_class_subject"),)

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)

    teacher = db.relationship("User")
    classroom = db.relationship("Classroom")
    subject = db.relationship("Subject")


class Score(db.Model):
    __tablename__ = "scores"
    __table_args__ = (db.UniqueConstraint("student_id", "classroom_id", "subject_id", name="uq_score_student_class_subject"),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    formative = db.Column(db.Numeric(4, 2), nullable=True)
    final = db.Column(db.Numeric(4, 2), nullable=True)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    student = db.relationship("User", foreign_keys=[student_id])
    classroom = db.relationship("Classroom")
    subject = db.relationship("Subject")
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    @property
    def course_score(self):
        if self.formative is None or self.final is None:
            return None
        return (float(self.formative) + float(self.final)) / 2


class GradeLock(db.Model):
    __tablename__ = "grade_locks"
    __table_args__ = (db.UniqueConstraint("classroom_id", "subject_id", "component", name="uq_grade_lock"),)

    id = db.Column(db.Integer, primary_key=True)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    component = db.Column(db.String(20), nullable=False)  # formative, final
    locked_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    locked_by = db.relationship("User")


class Announcement(db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    target_type = db.Column(db.String(20), nullable=False)  # all, teachers, students, class, user
    target_classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    target_classroom = db.relationship("Classroom")
    target_user = db.relationship("User", foreign_keys=[target_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class Objection(db.Model):
    __tablename__ = "objections"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    score_id = db.Column(db.Integer, db.ForeignKey("scores.id", ondelete="CASCADE"), nullable=False, index=True)
    component = db.Column(db.String(20), nullable=False)  # formative, final
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    response = db.Column(db.Text, nullable=True)
    previous_score = db.Column(db.Numeric(4, 2), nullable=True)
    changed_score = db.Column(db.Numeric(4, 2), nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    student = db.relationship("User", foreign_keys=[student_id])
    score = db.relationship("Score")
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id])
