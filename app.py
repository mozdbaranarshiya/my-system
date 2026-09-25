import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()


def database_url():
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        if value.startswith("postgres://"):
            value = "postgresql+psycopg://" + value[len("postgres://"):]
        elif value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://"):]
        return value
    if os.getenv("USE_SQLITE_DEV") == "1":
        return "sqlite:///school_dev.sqlite3"
    raise RuntimeError("DATABASE_URL تنظیم نشده است. فایل .env را بر اساس .env.example تکمیل کنید.")


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-me"),
    SQLALCHEMY_DATABASE_URI=database_url(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
if os.getenv("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "برای ادامه وارد سامانه شوید."
login_manager.login_message_category = "info"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    national_id = db.Column(db.String(10), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def is_active(self):
        return self.active

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)


class GradeLevel(db.Model):
    __tablename__ = "grade_levels"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class SchoolClass(db.Model):
    __tablename__ = "school_classes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    grade_level_id = db.Column(db.Integer, db.ForeignKey("grade_levels.id", ondelete="CASCADE"), nullable=False)
    representative_student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    grade_level = db.relationship("GradeLevel", backref=db.backref("classes", cascade="all, delete-orphan"))
    representative = db.relationship("User", foreign_keys=[representative_student_id])
    __table_args__ = (UniqueConstraint("name", "grade_level_id", name="uq_class_grade"),)


class Subject(db.Model):
    __tablename__ = "subjects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    grade_level_id = db.Column(db.Integer, db.ForeignKey("grade_levels.id", ondelete="CASCADE"), nullable=False)
    grade_level = db.relationship("GradeLevel", backref=db.backref("subjects", cascade="all, delete-orphan"))
    __table_args__ = (UniqueConstraint("name", "grade_level_id", name="uq_subject_grade"),)


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False)
    student = db.relationship("User", foreign_keys=[student_id])
    school_class = db.relationship("SchoolClass", backref=db.backref("enrollments", cascade="all, delete-orphan"))
    __table_args__ = (UniqueConstraint("student_id", "class_id", name="uq_student_class"),)


class TeachingAssignment(db.Model):
    __tablename__ = "teaching_assignments"
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    teacher = db.relationship("User", foreign_keys=[teacher_id])
    school_class = db.relationship("SchoolClass", backref=db.backref("assignments", cascade="all, delete-orphan"))
    subject = db.relationship("Subject", backref=db.backref("assignments", cascade="all, delete-orphan"))
    __table_args__ = (UniqueConstraint("class_id", "subject_id", name="uq_class_subject"),)


class Grade(db.Model):
    __tablename__ = "grades"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("teaching_assignments.id", ondelete="CASCADE"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    formative = db.Column(db.Numeric(4, 2), nullable=True)
    final = db.Column(db.Numeric(4, 2), nullable=True)
    entered_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    assignment = db.relationship("TeachingAssignment", backref=db.backref("grades", cascade="all, delete-orphan"))
    student = db.relationship("User", foreign_keys=[student_id])
    entered_by = db.relationship("User", foreign_keys=[entered_by_id])
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_grade_assignment_student"),)

    @property
    def lesson_score(self):
        if self.formative is None or self.final is None:
            return None
        return (self.formative + self.final) / Decimal("2")


class GradeLock(db.Model):
    __tablename__ = "grade_locks"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("teaching_assignments.id", ondelete="CASCADE"), nullable=False)
    component = db.Column(db.String(20), nullable=False)
    locked_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    assignment = db.relationship("TeachingAssignment", backref=db.backref("locks", cascade="all, delete-orphan"))
    locked_by = db.relationship("User", foreign_keys=[locked_by_id])
    __table_args__ = (UniqueConstraint("assignment_id", "component", name="uq_assignment_component_lock"),)


class Announcement(db.Model):
    __tablename__ = "announcements"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    audience = db.Column(db.String(30), nullable=False)
    target_class_id = db.Column(db.Integer, db.ForeignKey("school_classes.id", ondelete="SET NULL"), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    target_class = db.relationship("SchoolClass", foreign_keys=[target_class_id])
    target_user = db.relationship("User", foreign_keys=[target_user_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class Appeal(db.Model):
    __tablename__ = "appeals"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("teaching_assignments.id", ondelete="CASCADE"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    component = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)
    rejection_reason = db.Column(db.Text, nullable=True)
    original_score = db.Column(db.Numeric(4, 2), nullable=True)
    new_score = db.Column(db.Numeric(4, 2), nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    assignment = db.relationship("TeachingAssignment", backref=db.backref("appeals", cascade="all, delete-orphan"))
    student = db.relationship("User", foreign_keys=[student_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def valid_national_id(value):
    return bool(value and value.isdigit() and len(value) == 10)


def parse_score(value):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        score = Decimal(value)
    except InvalidOperation:
        raise ValueError("نمره باید عدد باشد.")
    if score < 0 or score > 20:
        raise ValueError("نمره باید بین ۰ تا ۲۰ باشد.")
    return score.quantize(Decimal("0.01"))


def component_label(component):
    return "تکوینی" if component == "formative" else "پایانی"


@app.context_processor
def helpers():
    return {"component_label": component_label}


def assignment_access_or_403(assignment):
    if current_user.role == "admin":
        return
    if current_user.role == "teacher" and assignment.teacher_id == current_user.id:
        return
    abort(403)


def student_classes(student_id):
    return [e.class_id for e in Enrollment.query.filter_by(student_id=student_id).all()]


def announcements_for(user):
    all_items = Announcement.query.order_by(Announcement.created_at.desc()).all()
    class_ids = set(student_classes(user.id)) if user.role == "student" else set()
    if user.role == "teacher":
        class_ids = {a.class_id for a in TeachingAssignment.query.filter_by(teacher_id=user.id).all()}
    result = []
    for item in all_items:
        if item.audience == "user" and item.target_user_id == user.id:
            result.append(item)
        elif item.audience == "all_students" and user.role == "student":
            result.append(item)
        elif item.audience == "all_teachers" and user.role == "teacher":
            result.append(item)
        elif item.audience == "class_students" and user.role == "student" and item.target_class_id in class_ids:
            result.append(item)
        elif item.audience == "class_teachers" and user.role == "teacher" and item.target_class_id in class_ids:
            result.append(item)
    return result


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        national_id = request.form.get("national_id", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(national_id=national_id, active=True).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("نام کاربری یا رمز عبور نادرست است.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    if current_user.role == "admin":
        stats = {
            "teachers": User.query.filter_by(role="teacher", active=True).count(),
            "students": User.query.filter_by(role="student", active=True).count(),
            "classes": SchoolClass.query.count(),
            "subjects": Subject.query.count(),
        }
        return render_template("dashboard_admin.html", stats=stats)
    if current_user.role == "teacher":
        assignments = TeachingAssignment.query.filter_by(teacher_id=current_user.id).order_by(TeachingAssignment.id.desc()).all()
        pending = Appeal.query.join(TeachingAssignment).filter(TeachingAssignment.teacher_id == current_user.id, Appeal.status == "pending").count()
        return render_template("dashboard_teacher.html", assignments=assignments, pending=pending, announcements=announcements_for(current_user)[:5])
    enrollments = Enrollment.query.filter_by(student_id=current_user.id).all()
    class_ids = [e.class_id for e in enrollments]
    assignments = TeachingAssignment.query.filter(TeachingAssignment.class_id.in_(class_ids)).all() if class_ids else []
    grade_map = {g.assignment_id: g for g in Grade.query.filter_by(student_id=current_user.id).all()}
    return render_template("dashboard_student.html", enrollments=enrollments, assignments=assignments, grade_map=grade_map, announcements=announcements_for(current_user)[:5])


@app.route("/admin/users", methods=["GET", "POST"])
@role_required("admin")
def admin_users():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        national_id = request.form.get("national_id", "").strip()
        role = request.form.get("role", "")
        if not full_name or role not in {"teacher", "student"}:
            flash("نام و نقش معتبر الزامی است.", "error")
        elif not valid_national_id(national_id):
            flash("کدملی باید ۱۰ رقم باشد.", "error")
        elif User.query.filter_by(national_id=national_id).first():
            flash("این کدملی قبلاً ثبت شده است.", "error")
        else:
            user = User(full_name=full_name, national_id=national_id, role=role)
            user.set_password(national_id)
            db.session.add(user)
            db.session.commit()
            flash("کاربر ساخته شد؛ نام کاربری و رمز اولیه همان کدملی است.", "success")
            return redirect(url_for("admin_users"))
    users = User.query.filter(User.role.in_(["teacher", "student"])).order_by(User.role, User.full_name).all()
    return render_template("users.html", users=users)


@app.post("/admin/users/<int:user_id>/edit")
@role_required("admin")
def admin_user_edit(user_id):
    user = db.get_or_404(User, user_id)
    if user.role not in {"teacher", "student"}:
        abort(400)
    full_name = request.form.get("full_name", "").strip()
    national_id = request.form.get("national_id", "").strip()
    new_password = request.form.get("new_password", "").strip()
    if not full_name or not valid_national_id(national_id):
        flash("نام و کدملی ۱۰ رقمی معتبر الزامی است.", "error")
        return redirect(url_for("admin_users"))
    duplicate = User.query.filter(User.national_id == national_id, User.id != user.id).first()
    if duplicate:
        flash("این کدملی متعلق به کاربر دیگری است.", "error")
        return redirect(url_for("admin_users"))
    user.full_name = full_name
    user.national_id = national_id
    if new_password:
        user.set_password(new_password)
    db.session.commit()
    flash("اطلاعات کاربر ویرایش شد.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/reset-password")
@role_required("admin")
def admin_user_reset_password(user_id):
    user = db.get_or_404(User, user_id)
    if user.role not in {"teacher", "student"}:
        abort(400)
    user.set_password(user.national_id)
    db.session.commit()
    flash("رمز عبور به کدملی فعلی کاربر بازنشانی شد.", "success")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/delete")
@role_required("admin")
def admin_user_delete(user_id):
    user = db.get_or_404(User, user_id)
    if user.role not in {"teacher", "student"}:
        abort(400)
    if user.role == "teacher":
        TeachingAssignment.query.filter_by(teacher_id=user.id).update({"teacher_id": None})
    db.session.delete(user)
    db.session.commit()
    flash("کاربر حذف شد.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/academics")
@role_required("admin")
def admin_academics():
    return render_template(
        "academics.html",
        levels=GradeLevel.query.order_by(GradeLevel.name).all(),
        classes=SchoolClass.query.order_by(SchoolClass.id.desc()).all(),
        subjects=Subject.query.order_by(Subject.id.desc()).all(),
        teachers=User.query.filter_by(role="teacher", active=True).order_by(User.full_name).all(),
        students=User.query.filter_by(role="student", active=True).order_by(User.full_name).all(),
        assignments=TeachingAssignment.query.order_by(TeachingAssignment.id.desc()).all(),
        enrollments=Enrollment.query.order_by(Enrollment.id.desc()).all(),
    )


@app.post("/admin/grade-level")
@role_required("admin")
def add_grade_level():
    name = request.form.get("name", "").strip()
    if name and not GradeLevel.query.filter_by(name=name).first():
        db.session.add(GradeLevel(name=name))
        db.session.commit()
        flash("پایه ثبت شد.", "success")
    else:
        flash("نام پایه نامعتبر یا تکراری است.", "error")
    return redirect(url_for("admin_academics"))


@app.post("/admin/class")
@role_required("admin")
def add_class():
    name = request.form.get("name", "").strip()
    grade_level_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_level_id):
        flash("نام کلاس و پایه معتبر الزامی است.", "error")
    elif SchoolClass.query.filter_by(name=name, grade_level_id=grade_level_id).first():
        flash("این کلاس در پایه انتخابی قبلاً ثبت شده است.", "error")
    else:
        db.session.add(SchoolClass(name=name, grade_level_id=grade_level_id))
        db.session.commit()
        flash("کلاس ثبت شد.", "success")
    return redirect(url_for("admin_academics"))


@app.post("/admin/subject")
@role_required("admin")
def add_subject():
    name = request.form.get("name", "").strip()
    grade_level_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_level_id):
        flash("نام درس و پایه معتبر الزامی است.", "error")
    elif Subject.query.filter_by(name=name, grade_level_id=grade_level_id).first():
        flash("این درس برای پایه انتخابی قبلاً ثبت شده است.", "error")
    else:
        db.session.add(Subject(name=name, grade_level_id=grade_level_id))
        db.session.commit()
        flash("درس ثبت شد.", "success")
    return redirect(url_for("admin_academics"))


@app.post("/admin/assignment")
@role_required("admin")
def add_assignment():
    class_id = request.form.get("class_id", type=int)
    subject_id = request.form.get("subject_id", type=int)
    teacher_id = request.form.get("teacher_id", type=int)
    school_class = db.session.get(SchoolClass, class_id)
    subject = db.session.get(Subject, subject_id)
    teacher = db.session.get(User, teacher_id)
    if not school_class or not subject or not teacher or teacher.role != "teacher":
        flash("کلاس، درس و معلم معتبر انتخاب کنید.", "error")
    elif school_class.grade_level_id != subject.grade_level_id:
        flash("درس باید متعلق به همان پایه کلاس باشد.", "error")
    else:
        assignment = TeachingAssignment.query.filter_by(class_id=class_id, subject_id=subject_id).first()
        if assignment:
            assignment.teacher_id = teacher_id
            flash("معلم درس به‌روزرسانی شد.", "success")
        else:
            db.session.add(TeachingAssignment(class_id=class_id, subject_id=subject_id, teacher_id=teacher_id))
            flash("معلم و درس به کلاس تخصیص داده شد.", "success")
        db.session.commit()
    return redirect(url_for("admin_academics"))


@app.post("/admin/enrollment")
@role_required("admin")
def add_enrollment():
    class_id = request.form.get("class_id", type=int)
    student_id = request.form.get("student_id", type=int)
    school_class = db.session.get(SchoolClass, class_id)
    student = db.session.get(User, student_id)
    if not school_class or not student or student.role != "student":
        flash("دانش‌آموز و کلاس معتبر انتخاب کنید.", "error")
    elif Enrollment.query.filter_by(class_id=class_id, student_id=student_id).first():
        flash("دانش‌آموز قبلاً در این کلاس ثبت شده است.", "error")
    else:
        Enrollment.query.filter_by(student_id=student_id).delete()
        db.session.add(Enrollment(class_id=class_id, student_id=student_id))
        db.session.commit()
        flash("دانش‌آموز در کلاس ثبت شد.", "success")
    return redirect(url_for("admin_academics"))


@app.post("/admin/representative")
@role_required("admin")
def set_representative():
    class_id = request.form.get("class_id", type=int)
    student_id = request.form.get("student_id", type=int)
    school_class = db.session.get(SchoolClass, class_id)
    enrollment = Enrollment.query.filter_by(class_id=class_id, student_id=student_id).first()
    if not school_class or not enrollment:
        flash("نماینده باید از دانش‌آموزان همان کلاس باشد.", "error")
    else:
        school_class.representative_student_id = student_id
        db.session.commit()
        flash("نماینده کلاس ثبت شد.", "success")
    return redirect(url_for("admin_academics"))


@app.post("/admin/assignment/<int:assignment_id>/delete")
@role_required("admin")
def delete_assignment(assignment_id):
    item = db.get_or_404(TeachingAssignment, assignment_id)
    db.session.delete(item)
    db.session.commit()
    flash("تخصیص حذف شد.", "success")
    return redirect(url_for("admin_academics"))


@app.post("/admin/enrollment/<int:enrollment_id>/delete")
@role_required("admin")
def delete_enrollment(enrollment_id):
    item = db.get_or_404(Enrollment, enrollment_id)
    if item.school_class.representative_student_id == item.student_id:
        item.school_class.representative_student_id = None
    db.session.delete(item)
    db.session.commit()
    flash("دانش‌آموز از کلاس حذف شد.", "success")
    return redirect(url_for("admin_academics"))


@app.route("/grades/<int:assignment_id>", methods=["GET", "POST"])
@role_required("admin", "teacher")
def grades(assignment_id):
    assignment = db.get_or_404(TeachingAssignment, assignment_id)
    assignment_access_or_403(assignment)
    enrollments = Enrollment.query.filter_by(class_id=assignment.class_id).join(User, Enrollment.student_id == User.id).order_by(User.full_name).all()
    locks = {lock.component: lock for lock in GradeLock.query.filter_by(assignment_id=assignment.id).all()}

    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action in {"save", "finalize_formative", "finalize_final"}:
                for enrollment in enrollments:
                    grade = Grade.query.filter_by(assignment_id=assignment.id, student_id=enrollment.student_id).first()
                    if not grade:
                        grade = Grade(assignment_id=assignment.id, student_id=enrollment.student_id)
                        db.session.add(grade)
                    if "formative" not in locks:
                        grade.formative = parse_score(request.form.get(f"formative_{enrollment.student_id}"))
                    if "final" not in locks:
                        grade.final = parse_score(request.form.get(f"final_{enrollment.student_id}"))
                    grade.entered_by_id = current_user.id
                if action.startswith("finalize_"):
                    component = action.replace("finalize_", "")
                    if current_user.role != "teacher":
                        flash("مدیر برای قفل‌کردن از ابزار قفل نمرات استفاده کند.", "error")
                        db.session.rollback()
                        return redirect(url_for("grades", assignment_id=assignment.id))
                    if component not in locks:
                        db.session.add(GradeLock(assignment_id=assignment.id, component=component, locked_by_id=current_user.id))
                    flash(f"نمرات {component_label(component)} نهایی و قفل شد.", "success")
                else:
                    flash("نمرات به‌صورت موقت ذخیره شد.", "success")
                db.session.commit()
            elif action == "lock" and current_user.role == "admin":
                component = request.form.get("component")
                components = ["formative", "final"] if component == "both" else [component]
                for comp in components:
                    if comp in {"formative", "final"} and comp not in locks:
                        db.session.add(GradeLock(assignment_id=assignment.id, component=comp, locked_by_id=current_user.id))
                db.session.commit()
                flash("بخش انتخاب‌شده قفل شد.", "success")
            elif action == "unlock" and current_user.role == "admin":
                component = request.form.get("component")
                GradeLock.query.filter_by(assignment_id=assignment.id, component=component).delete()
                db.session.commit()
                flash(f"بخش {component_label(component)} بازگشایی شد.", "success")
            else:
                abort(400)
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("grades", assignment_id=assignment.id))

    grade_map = {g.student_id: g for g in Grade.query.filter_by(assignment_id=assignment.id).all()}
    return render_template("grades.html", assignment=assignment, enrollments=enrollments, grade_map=grade_map, locks=locks)


@app.route("/announcements", methods=["GET", "POST"])
@login_required
def announcements():
    if current_user.role == "admin":
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            body = request.form.get("body", "").strip()
            audience = request.form.get("audience", "")
            target_class_id = request.form.get("target_class_id", type=int)
            target_user_id = request.form.get("target_user_id", type=int)
            allowed = {"all_students", "all_teachers", "class_students", "class_teachers", "user"}
            if not title or not body or audience not in allowed:
                flash("عنوان، متن و مخاطب معتبر الزامی است.", "error")
            elif audience.startswith("class_") and not db.session.get(SchoolClass, target_class_id):
                flash("برای اعلان کلاسی، کلاس را انتخاب کنید.", "error")
            elif audience == "user" and not db.session.get(User, target_user_id):
                flash("برای اعلان فردی، کاربر را انتخاب کنید.", "error")
            else:
                db.session.add(Announcement(
                    title=title,
                    body=body,
                    audience=audience,
                    target_class_id=target_class_id if audience.startswith("class_") else None,
                    target_user_id=target_user_id if audience == "user" else None,
                    created_by_id=current_user.id,
                ))
                db.session.commit()
                flash("اطلاعیه ارسال شد.", "success")
                return redirect(url_for("announcements"))
        items = Announcement.query.order_by(Announcement.created_at.desc()).all()
        return render_template(
            "announcements.html",
            items=items,
            classes=SchoolClass.query.order_by(SchoolClass.name).all(),
            users=User.query.filter(User.role.in_(["teacher", "student"]), User.active.is_(True)).order_by(User.full_name).all(),
        )
    return render_template("announcements.html", items=announcements_for(current_user), classes=[], users=[])


@app.post("/announcements/<int:announcement_id>/delete")
@role_required("admin")
def announcement_delete(announcement_id):
    item = db.get_or_404(Announcement, announcement_id)
    db.session.delete(item)
    db.session.commit()
    flash("اطلاعیه حذف شد.", "success")
    return redirect(url_for("announcements"))


@app.route("/appeals", methods=["GET", "POST"])
@login_required
def appeals():
    if current_user.role == "student":
        class_ids = student_classes(current_user.id)
        assignments = TeachingAssignment.query.filter(TeachingAssignment.class_id.in_(class_ids)).all() if class_ids else []
        if request.method == "POST":
            assignment_id = request.form.get("assignment_id", type=int)
            component = request.form.get("component", "")
            reason = request.form.get("reason", "").strip()
            assignment = db.session.get(TeachingAssignment, assignment_id)
            if not assignment or assignment.class_id not in class_ids or component not in {"formative", "final"} or not reason:
                flash("درس، نوع نمره و علت اعتراض را کامل کنید.", "error")
            elif Appeal.query.filter_by(assignment_id=assignment_id, student_id=current_user.id, component=component, status="pending").first():
                flash("برای این بخش یک اعتراض در انتظار بررسی دارید.", "error")
            else:
                grade = Grade.query.filter_by(assignment_id=assignment_id, student_id=current_user.id).first()
                original = getattr(grade, component) if grade else None
                db.session.add(Appeal(assignment_id=assignment_id, student_id=current_user.id, component=component, reason=reason, original_score=original))
                db.session.commit()
                flash("اعتراض ثبت شد.", "success")
                return redirect(url_for("appeals"))
        items = Appeal.query.filter_by(student_id=current_user.id).order_by(Appeal.created_at.desc()).all()
        return render_template("appeals.html", items=items, assignments=assignments)
    if current_user.role == "teacher":
        items = Appeal.query.join(TeachingAssignment).filter(TeachingAssignment.teacher_id == current_user.id).order_by(Appeal.created_at.desc()).all()
        return render_template("appeals.html", items=items, assignments=[])
    items = Appeal.query.order_by(Appeal.created_at.desc()).all()
    return render_template("appeals.html", items=items, assignments=[])


@app.post("/appeals/<int:appeal_id>/review")
@role_required("teacher")
def review_appeal(appeal_id):
    appeal = db.get_or_404(Appeal, appeal_id)
    if appeal.assignment.teacher_id != current_user.id or appeal.status != "pending":
        abort(403)
    decision = request.form.get("decision")
    if decision == "approve":
        if GradeLock.query.filter_by(assignment_id=appeal.assignment_id, component=appeal.component).first():
            flash("این بخش نمره قفل است؛ مدیر باید ابتدا آن را بازگشایی کند.", "error")
            return redirect(url_for("appeals"))
        try:
            new_score = parse_score(request.form.get("new_score"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("appeals"))
        if new_score is None:
            flash("در صورت تأیید اعتراض، وارد کردن نمره جدید الزامی است.", "error")
            return redirect(url_for("appeals"))
        grade = Grade.query.filter_by(assignment_id=appeal.assignment_id, student_id=appeal.student_id).first()
        if not grade:
            grade = Grade(assignment_id=appeal.assignment_id, student_id=appeal.student_id)
            db.session.add(grade)
        setattr(grade, appeal.component, new_score)
        grade.entered_by_id = current_user.id
        appeal.status = "approved"
        appeal.new_score = new_score
        appeal.rejection_reason = None
        flash("اعتراض تأیید و نمره تغییر کرد.", "success")
    elif decision == "reject":
        rejection_reason = request.form.get("rejection_reason", "").strip()
        if not rejection_reason:
            flash("برای رد اعتراض، علت رد الزامی است.", "error")
            return redirect(url_for("appeals"))
        appeal.status = "rejected"
        appeal.rejection_reason = rejection_reason
        flash("اعتراض رد شد و علت ثبت گردید.", "success")
    else:
        abort(400)
    appeal.reviewed_by_id = current_user.id
    appeal.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("appeals"))


@app.cli.command("init-db")
def init_db_command():
    """Create tables and the initial admin account."""
    db.create_all()
    national_id = os.getenv("ADMIN_NATIONAL_ID", "").strip()
    full_name = os.getenv("ADMIN_NAME", "مدیر سامانه").strip() or "مدیر سامانه"
    if not valid_national_id(national_id):
        print("خطا: ADMIN_NATIONAL_ID باید یک کدملی ۱۰ رقمی باشد.")
        return
    user = User.query.filter_by(national_id=national_id).first()
    if not user:
        user = User(full_name=full_name, national_id=national_id, role="admin")
        user.set_password(national_id)
        db.session.add(user)
        db.session.commit()
        print("مدیر اولیه ساخته شد. نام کاربری و رمز اولیه همان کدملی است.")
    else:
        print("کاربر مدیر قبلاً وجود دارد.")


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="شما به این بخش دسترسی ندارید."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="صفحه موردنظر پیدا نشد."), 404


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
