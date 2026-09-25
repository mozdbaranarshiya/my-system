from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from . import db
from .models import (
    Announcement,
    Classroom,
    GradeLevel,
    GradeLock,
    Objection,
    Score,
    StudentProfile,
    Subject,
    TeacherAssignment,
    User,
)
from .services import (
    announcements_for_user,
    can_access_gradebook,
    is_component_locked,
    parse_score,
    require_role,
    students_in_classroom,
    teacher_has_assignment,
    valid_national_id,
)

bp = Blueprint("main", __name__)


def _commit_with_message(success="تغییرات با موفقیت ذخیره شد."):
    try:
        db.session.commit()
        flash(success, "success")
        return True
    except IntegrityError:
        db.session.rollback()
        flash("اطلاعات تکراری یا ناسازگار است. لطفاً ورودی‌ها را بررسی کنید.", "danger")
        return False


def _get_class_subject_or_404(classroom_id, subject_id):
    classroom = db.session.get(Classroom, classroom_id)
    subject = db.session.get(Subject, subject_id)
    if not classroom or not subject or classroom.grade_level_id != subject.grade_level_id:
        abort(404)
    return classroom, subject


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user)
            return redirect(url_for("main.dashboard"))
        flash("نام کاربری یا رمز عبور صحیح نیست.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("از سامانه خارج شدید.", "info")
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    data = {}
    if current_user.role == "admin":
        data = {
            "teachers": User.query.filter_by(role="teacher").count(),
            "students": User.query.filter_by(role="student").count(),
            "classes": Classroom.query.count(),
            "pending_objections": Objection.query.filter_by(status="pending").count(),
        }
    elif current_user.role == "teacher":
        assignment_ids = [a.id for a in TeacherAssignment.query.filter_by(teacher_id=current_user.id).all()]
        data = {"assignments": len(assignment_ids), "announcements": len(announcements_for_user(current_user))}
    else:
        data = {"announcements": len(announcements_for_user(current_user))}
    return render_template("dashboard.html", data=data)


# -------------------------- Admin: users --------------------------
@bp.route("/admin/users")
@login_required
def admin_users():
    require_role("admin")
    users = User.query.order_by(User.role.asc(), User.full_name.asc()).all()
    classrooms = Classroom.query.join(GradeLevel).order_by(GradeLevel.sort_order, Classroom.name).all()
    return render_template("users.html", users=users, classrooms=classrooms)


@bp.route("/admin/users/create", methods=["POST"])
@login_required
def admin_user_create():
    require_role("admin")
    national_id = request.form.get("national_id", "").strip()
    full_name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "").strip()
    classroom_id = request.form.get("classroom_id", type=int)

    if not full_name or role not in {"teacher", "student"} or not valid_national_id(national_id):
        flash("نام، نقش و کد ملی ۱۰ رقمی معتبر الزامی است.", "danger")
        return redirect(url_for("main.admin_users"))
    if role == "student" and not db.session.get(Classroom, classroom_id):
        flash("برای دانش‌آموز باید کلاس معتبر انتخاب شود.", "danger")
        return redirect(url_for("main.admin_users"))

    user = User(national_id=national_id, username=national_id, full_name=full_name, role=role)
    user.set_password(national_id)
    db.session.add(user)
    try:
        db.session.flush()
        if role == "student":
            db.session.add(StudentProfile(user_id=user.id, classroom_id=classroom_id))
        db.session.commit()
        flash("کاربر ایجاد شد. نام کاربری و رمز اولیه همان کد ملی است.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("این کد ملی یا نام کاربری قبلاً ثبت شده است.", "danger")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@login_required
def admin_user_edit(user_id):
    require_role("admin")
    user = db.session.get(User, user_id) or abort(404)
    full_name = request.form.get("full_name", "").strip()
    classroom_id = request.form.get("classroom_id", type=int)
    active = request.form.get("is_active") == "on"
    if not full_name:
        flash("نام نمی‌تواند خالی باشد.", "danger")
        return redirect(url_for("main.admin_users"))
    user.full_name = full_name
    user.is_active_flag = active
    if user.role == "student":
        classroom = db.session.get(Classroom, classroom_id)
        if not classroom:
            flash("کلاس معتبر انتخاب کنید.", "danger")
            return redirect(url_for("main.admin_users"))
        user.student_profile.classroom_id = classroom.id
    _commit_with_message("اطلاعات کاربر ویرایش شد.")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/credentials", methods=["POST"])
@login_required
def admin_user_credentials(user_id):
    require_role("admin")
    user = db.session.get(User, user_id) or abort(404)
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or len(password) < 6:
        flash("نام کاربری الزامی و رمز باید حداقل ۶ نویسه باشد.", "danger")
        return redirect(url_for("main.admin_users"))
    user.username = username
    user.set_password(password)
    _commit_with_message("نام کاربری و رمز عبور توسط مدیر تغییر کرد.")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/reset", methods=["POST"])
@login_required
def admin_user_reset(user_id):
    require_role("admin")
    user = db.session.get(User, user_id) or abort(404)
    user.username = user.national_id
    user.set_password(user.national_id)
    _commit_with_message("نام کاربری و رمز عبور به کد ملی بازنشانی شد.")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
def admin_user_delete(user_id):
    require_role("admin")
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id or user.role == "admin":
        flash("حذف این حساب مجاز نیست.", "danger")
        return redirect(url_for("main.admin_users"))
    db.session.delete(user)
    _commit_with_message("کاربر حذف شد.")
    return redirect(url_for("main.admin_users"))


# -------------------------- Admin: school structure --------------------------
@bp.route("/admin/structure")
@login_required
def admin_structure():
    require_role("admin")
    grades = GradeLevel.query.order_by(GradeLevel.sort_order, GradeLevel.name).all()
    classrooms = Classroom.query.join(GradeLevel).order_by(GradeLevel.sort_order, Classroom.name).all()
    subjects = Subject.query.join(GradeLevel).order_by(GradeLevel.sort_order, Subject.name).all()
    return render_template("structure.html", grades=grades, classrooms=classrooms, subjects=subjects)


@bp.route("/admin/grades/create", methods=["POST"])
@login_required
def admin_grade_create():
    require_role("admin")
    name = request.form.get("name", "").strip()
    sort_order = request.form.get("sort_order", 0, type=int)
    if not name:
        flash("نام پایه الزامی است.", "danger")
    else:
        db.session.add(GradeLevel(name=name, sort_order=sort_order))
        _commit_with_message("پایه ثبت شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/grades/<int:item_id>/edit", methods=["POST"])
@login_required
def admin_grade_edit(item_id):
    require_role("admin")
    item = db.session.get(GradeLevel, item_id) or abort(404)
    item.name = request.form.get("name", "").strip()
    item.sort_order = request.form.get("sort_order", 0, type=int)
    _commit_with_message("پایه ویرایش شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/grades/<int:item_id>/delete", methods=["POST"])
@login_required
def admin_grade_delete(item_id):
    require_role("admin")
    item = db.session.get(GradeLevel, item_id) or abort(404)
    if item.classrooms or item.subjects:
        flash("ابتدا کلاس‌ها و درس‌های این پایه را حذف کنید.", "danger")
    else:
        db.session.delete(item)
        _commit_with_message("پایه حذف شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/classes/create", methods=["POST"])
@login_required
def admin_class_create():
    require_role("admin")
    name = request.form.get("name", "").strip()
    grade_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_id):
        flash("نام کلاس و پایه معتبر الزامی است.", "danger")
    else:
        db.session.add(Classroom(name=name, grade_level_id=grade_id))
        _commit_with_message("کلاس ثبت شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/classes/<int:item_id>/edit", methods=["POST"])
@login_required
def admin_class_edit(item_id):
    require_role("admin")
    item = db.session.get(Classroom, item_id) or abort(404)
    name = request.form.get("name", "").strip()
    grade_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_id):
        flash("اطلاعات کلاس معتبر نیست.", "danger")
    elif item.students and grade_id != item.grade_level_id:
        flash("تا زمانی که دانش‌آموز در کلاس است، پایه کلاس قابل تغییر نیست.", "danger")
    else:
        item.name = name
        item.grade_level_id = grade_id
        _commit_with_message("کلاس ویرایش شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/classes/<int:item_id>/delete", methods=["POST"])
@login_required
def admin_class_delete(item_id):
    require_role("admin")
    item = db.session.get(Classroom, item_id) or abort(404)
    if item.students:
        flash("کلاس دارای دانش‌آموز است و قابل حذف نیست.", "danger")
    else:
        db.session.delete(item)
        _commit_with_message("کلاس حذف شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/subjects/create", methods=["POST"])
@login_required
def admin_subject_create():
    require_role("admin")
    name = request.form.get("name", "").strip()
    grade_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_id):
        flash("نام درس و پایه معتبر الزامی است.", "danger")
    else:
        db.session.add(Subject(name=name, grade_level_id=grade_id))
        _commit_with_message("درس ثبت شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/subjects/<int:item_id>/edit", methods=["POST"])
@login_required
def admin_subject_edit(item_id):
    require_role("admin")
    item = db.session.get(Subject, item_id) or abort(404)
    name = request.form.get("name", "").strip()
    grade_id = request.form.get("grade_level_id", type=int)
    if not name or not db.session.get(GradeLevel, grade_id):
        flash("اطلاعات درس معتبر نیست.", "danger")
    elif TeacherAssignment.query.filter_by(subject_id=item.id).first() and grade_id != item.grade_level_id:
        flash("درس تخصیص داده شده است؛ پایه آن قابل تغییر نیست.", "danger")
    else:
        item.name = name
        item.grade_level_id = grade_id
        _commit_with_message("درس ویرایش شد.")
    return redirect(url_for("main.admin_structure"))


@bp.route("/admin/subjects/<int:item_id>/delete", methods=["POST"])
@login_required
def admin_subject_delete(item_id):
    require_role("admin")
    item = db.session.get(Subject, item_id) or abort(404)
    if TeacherAssignment.query.filter_by(subject_id=item.id).first() or Score.query.filter_by(subject_id=item.id).first():
        flash("این درس دارای تخصیص یا نمره است و قابل حذف نیست.", "danger")
    else:
        db.session.delete(item)
        _commit_with_message("درس حذف شد.")
    return redirect(url_for("main.admin_structure"))


# -------------------------- Admin: assignments and representative --------------------------
@bp.route("/admin/assignments")
@login_required
def admin_assignments():
    require_role("admin")
    assignments = TeacherAssignment.query.order_by(TeacherAssignment.id.desc()).all()
    teachers = User.query.filter_by(role="teacher", is_active_flag=True).order_by(User.full_name).all()
    classrooms = Classroom.query.join(GradeLevel).order_by(GradeLevel.sort_order, Classroom.name).all()
    subjects = Subject.query.join(GradeLevel).order_by(GradeLevel.sort_order, Subject.name).all()
    return render_template(
        "assignments.html",
        assignments=assignments,
        teachers=teachers,
        classrooms=classrooms,
        subjects=subjects,
    )


@bp.route("/admin/assignments/create", methods=["POST"])
@login_required
def admin_assignment_create():
    require_role("admin")
    teacher_id = request.form.get("teacher_id", type=int)
    classroom_id = request.form.get("classroom_id", type=int)
    subject_id = request.form.get("subject_id", type=int)
    teacher = db.session.get(User, teacher_id)
    classroom, subject = _get_class_subject_or_404(classroom_id, subject_id)
    if not teacher or teacher.role != "teacher":
        flash("معلم معتبر انتخاب کنید.", "danger")
    elif classroom.grade_level_id != subject.grade_level_id:
        flash("درس باید متعلق به پایه همان کلاس باشد.", "danger")
    else:
        db.session.add(TeacherAssignment(teacher_id=teacher.id, classroom_id=classroom.id, subject_id=subject.id))
        _commit_with_message("معلم و درس به کلاس تخصیص داده شد.")
    return redirect(url_for("main.admin_assignments"))


@bp.route("/admin/assignments/<int:item_id>/delete", methods=["POST"])
@login_required
def admin_assignment_delete(item_id):
    require_role("admin")
    item = db.session.get(TeacherAssignment, item_id) or abort(404)
    db.session.delete(item)
    _commit_with_message("تخصیص حذف شد.")
    return redirect(url_for("main.admin_assignments"))


@bp.route("/admin/classes/<int:classroom_id>/representative", methods=["POST"])
@login_required
def admin_set_representative(classroom_id):
    require_role("admin")
    classroom = db.session.get(Classroom, classroom_id) or abort(404)
    student_id = request.form.get("student_id", type=int)
    if not student_id:
        classroom.representative_student_id = None
        _commit_with_message("نماینده کلاس حذف شد.")
    else:
        student = db.session.get(User, student_id)
        if not student or not student.student_profile or student.student_profile.classroom_id != classroom.id:
            flash("دانش‌آموز انتخاب‌شده عضو این کلاس نیست.", "danger")
        else:
            classroom.representative_student_id = student.id
            _commit_with_message("نماینده کلاس ثبت شد.")
    return redirect(url_for("main.admin_structure"))


# -------------------------- Announcements --------------------------
@bp.route("/announcements")
@login_required
def announcements():
    items = Announcement.query.order_by(Announcement.created_at.desc()).all() if current_user.role == "admin" else announcements_for_user(current_user)
    classrooms = Classroom.query.order_by(Classroom.name).all() if current_user.role == "admin" else []
    users = User.query.filter(User.role.in_(["teacher", "student"])).order_by(User.full_name).all() if current_user.role == "admin" else []
    return render_template("announcements.html", announcements=items, classrooms=classrooms, users=users)


@bp.route("/admin/announcements/create", methods=["POST"])
@login_required
def admin_announcement_create():
    require_role("admin")
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    target_type = request.form.get("target_type", "").strip()
    target_classroom_id = request.form.get("target_classroom_id", type=int)
    target_user_id = request.form.get("target_user_id", type=int)
    if not title or not body or target_type not in {"all", "teachers", "students", "class", "user"}:
        flash("عنوان، متن و نوع مخاطب معتبر الزامی است.", "danger")
        return redirect(url_for("main.announcements"))
    if target_type == "class" and not db.session.get(Classroom, target_classroom_id):
        flash("کلاس مخاطب معتبر نیست.", "danger")
        return redirect(url_for("main.announcements"))
    if target_type == "user" and not db.session.get(User, target_user_id):
        flash("کاربر مخاطب معتبر نیست.", "danger")
        return redirect(url_for("main.announcements"))
    item = Announcement(
        title=title,
        body=body,
        target_type=target_type,
        target_classroom_id=target_classroom_id if target_type == "class" else None,
        target_user_id=target_user_id if target_type == "user" else None,
        created_by_id=current_user.id,
    )
    db.session.add(item)
    _commit_with_message("اطلاعیه ارسال شد.")
    return redirect(url_for("main.announcements"))


@bp.route("/admin/announcements/<int:item_id>/delete", methods=["POST"])
@login_required
def admin_announcement_delete(item_id):
    require_role("admin")
    item = db.session.get(Announcement, item_id) or abort(404)
    db.session.delete(item)
    _commit_with_message("اطلاعیه حذف شد.")
    return redirect(url_for("main.announcements"))


# -------------------------- Gradebook --------------------------
@bp.route("/gradebooks")
@login_required
def gradebooks():
    if current_user.role == "admin":
        assignments = TeacherAssignment.query.order_by(TeacherAssignment.classroom_id, TeacherAssignment.subject_id).all()
        # Also show valid class/subject pairs even before a teacher is assigned.
        pairs = []
        for classroom in Classroom.query.order_by(Classroom.name).all():
            for subject in Subject.query.filter_by(grade_level_id=classroom.grade_level_id).order_by(Subject.name).all():
                pairs.append((classroom, subject))
        return render_template("gradebooks.html", assignments=assignments, pairs=pairs)
    if current_user.role == "teacher":
        assignments = TeacherAssignment.query.filter_by(teacher_id=current_user.id).order_by(TeacherAssignment.classroom_id).all()
        return render_template("gradebooks.html", assignments=assignments, pairs=[])
    return redirect(url_for("main.student_report"))


@bp.route("/gradebook/<int:classroom_id>/<int:subject_id>", methods=["GET", "POST"])
@login_required
def gradebook(classroom_id, subject_id):
    classroom, subject = _get_class_subject_or_404(classroom_id, subject_id)
    if not can_access_gradebook(current_user, classroom_id, subject_id):
        abort(403)

    students = students_in_classroom(classroom_id)
    formative_locked = is_component_locked(classroom_id, subject_id, "formative")
    final_locked = is_component_locked(classroom_id, subject_id, "final")

    if request.method == "POST":
        action = request.form.get("action", "save")
        teacher_actions = {"save", "finalize_formative", "finalize_final"}
        admin_actions = {"save", "lock_formative", "lock_final", "lock_both", "unlock_formative", "unlock_final", "unlock_both"}
        if current_user.role == "teacher" and action not in teacher_actions:
            abort(403)
        if current_user.role == "admin" and action not in admin_actions:
            abort(403)

        if action == "save":
            try:
                for student in students:
                    score = Score.query.filter_by(student_id=student.id, classroom_id=classroom_id, subject_id=subject_id).first()
                    if not score:
                        score = Score(student_id=student.id, classroom_id=classroom_id, subject_id=subject_id)
                        db.session.add(score)
                    if not formative_locked:
                        score.formative = parse_score(request.form.get(f"formative_{student.id}"))
                    if not final_locked:
                        score.final = parse_score(request.form.get(f"final_{student.id}"))
                    score.updated_by_id = current_user.id
                db.session.commit()
                flash("نمرات به صورت موقت ذخیره شدند.", "success")
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            return redirect(url_for("main.gradebook", classroom_id=classroom_id, subject_id=subject_id))

        lock_components = []
        unlock_components = []
        if action in {"finalize_formative", "lock_formative"}:
            lock_components = ["formative"]
        elif action in {"finalize_final", "lock_final"}:
            lock_components = ["final"]
        elif action == "lock_both":
            lock_components = ["formative", "final"]
        elif action == "unlock_formative":
            unlock_components = ["formative"]
        elif action == "unlock_final":
            unlock_components = ["final"]
        elif action == "unlock_both":
            unlock_components = ["formative", "final"]
        else:
            abort(400)

        if unlock_components and current_user.role != "admin":
            abort(403)

        # Teacher "finalize" means save the visible values for that component first, then lock it.
        if action in {"finalize_formative", "finalize_final"}:
            component = "formative" if action == "finalize_formative" else "final"
            if is_component_locked(classroom_id, subject_id, component):
                flash("این بخش از نمرات قبلاً قفل شده است و فقط مدیر می‌تواند آن را بازگشایی کند.", "danger")
                return redirect(url_for("main.gradebook", classroom_id=classroom_id, subject_id=subject_id))
            try:
                for student in students:
                    score = Score.query.filter_by(
                        student_id=student.id, classroom_id=classroom_id, subject_id=subject_id
                    ).first()
                    if not score:
                        score = Score(student_id=student.id, classroom_id=classroom_id, subject_id=subject_id)
                        db.session.add(score)
                    score_value = parse_score(request.form.get(f"{component}_{student.id}"))
                    setattr(score, component, score_value)
                    score.updated_by_id = current_user.id
                db.session.flush()
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return redirect(url_for("main.gradebook", classroom_id=classroom_id, subject_id=subject_id))

        for component in lock_components:
            if not is_component_locked(classroom_id, subject_id, component):
                db.session.add(GradeLock(classroom_id=classroom_id, subject_id=subject_id, component=component, locked_by_id=current_user.id))
        if unlock_components:
            GradeLock.query.filter(
                GradeLock.classroom_id == classroom_id,
                GradeLock.subject_id == subject_id,
                GradeLock.component.in_(unlock_components),
            ).delete(synchronize_session=False)
        db.session.commit()
        flash("وضعیت قفل نمرات به‌روزرسانی شد.", "success")
        return redirect(url_for("main.gradebook", classroom_id=classroom_id, subject_id=subject_id))

    score_map = {s.student_id: s for s in Score.query.filter_by(classroom_id=classroom_id, subject_id=subject_id).all()}
    return render_template(
        "gradebook.html",
        classroom=classroom,
        subject=subject,
        students=students,
        score_map=score_map,
        formative_locked=formative_locked,
        final_locked=final_locked,
    )


# -------------------------- Student pages --------------------------
@bp.route("/student/report")
@login_required
def student_report():
    require_role("student")
    profile = current_user.student_profile
    scores = Score.query.filter_by(student_id=current_user.id, classroom_id=profile.classroom_id).order_by(Score.subject_id).all()
    return render_template("student_report.html", scores=scores, classroom=profile.classroom)


@bp.route("/student/teachers")
@login_required
def student_teachers():
    require_role("student")
    profile = current_user.student_profile
    assignments = TeacherAssignment.query.filter_by(classroom_id=profile.classroom_id).order_by(TeacherAssignment.subject_id).all()
    return render_template("student_teachers.html", assignments=assignments, classroom=profile.classroom)


# -------------------------- Objections --------------------------
@bp.route("/objections")
@login_required
def objections():
    if current_user.role == "student":
        items = Objection.query.filter_by(student_id=current_user.id).order_by(Objection.created_at.desc()).all()
        profile = current_user.student_profile
        scores = Score.query.filter_by(student_id=current_user.id, classroom_id=profile.classroom_id).order_by(Score.subject_id).all()
    elif current_user.role == "teacher":
        assigned_pairs = [(a.classroom_id, a.subject_id) for a in TeacherAssignment.query.filter_by(teacher_id=current_user.id).all()]
        items = [o for o in Objection.query.order_by(Objection.created_at.desc()).all() if (o.score.classroom_id, o.score.subject_id) in assigned_pairs]
        scores = []
    else:
        items = Objection.query.order_by(Objection.created_at.desc()).all()
        scores = []
    return render_template("objections.html", objections=items, scores=scores)


@bp.route("/student/objections/create", methods=["POST"])
@login_required
def student_objection_create():
    require_role("student")
    score_id = request.form.get("score_id", type=int)
    component = request.form.get("component", "").strip()
    reason = request.form.get("reason", "").strip()
    score = db.session.get(Score, score_id)
    if not score or score.student_id != current_user.id or component not in {"formative", "final"} or not reason:
        flash("اطلاعات اعتراض کامل یا معتبر نیست.", "danger")
        return redirect(url_for("main.objections"))
    if getattr(score, component) is None:
        flash("برای بخشی که هنوز نمره ندارد امکان اعتراض وجود ندارد.", "danger")
        return redirect(url_for("main.objections"))
    duplicate = Objection.query.filter_by(student_id=current_user.id, score_id=score.id, component=component, status="pending").first()
    if duplicate:
        flash("برای این نمره یک اعتراض در حال بررسی دارید.", "warning")
        return redirect(url_for("main.objections"))
    db.session.add(Objection(student_id=current_user.id, score_id=score.id, component=component, reason=reason))
    _commit_with_message("اعتراض ثبت شد.")
    return redirect(url_for("main.objections"))


@bp.route("/objections/<int:item_id>/resolve", methods=["POST"])
@login_required
def objection_resolve(item_id):
    require_role("teacher", "admin")
    item = db.session.get(Objection, item_id) or abort(404)
    if item.status != "pending":
        flash("این اعتراض قبلاً بررسی شده است.", "warning")
        return redirect(url_for("main.objections"))
    score = item.score
    if current_user.role == "teacher" and not teacher_has_assignment(current_user.id, score.classroom_id, score.subject_id):
        abort(403)

    decision = request.form.get("decision", "")
    response = request.form.get("response", "").strip()
    if decision == "reject":
        if not response:
            flash("برای رد اعتراض، علت رد الزامی است.", "danger")
            return redirect(url_for("main.objections"))
        item.status = "rejected"
        item.response = response
    elif decision == "approve":
        if is_component_locked(score.classroom_id, score.subject_id, item.component):
            flash("این بخش از نمرات قفل است؛ مدیر باید ابتدا آن را بازگشایی کند.", "danger")
            return redirect(url_for("main.objections"))
        try:
            new_score = parse_score(request.form.get("new_score"))
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("main.objections"))
        if new_score is None:
            flash("در صورت تأیید اعتراض، ثبت نمره جدید الزامی است.", "danger")
            return redirect(url_for("main.objections"))
        item.previous_score = getattr(score, item.component)
        setattr(score, item.component, new_score)
        score.updated_by_id = current_user.id
        item.changed_score = new_score
        item.status = "approved"
        item.response = response or "اعتراض تأیید و نمره اصلاح شد."
    else:
        abort(400)

    item.resolved_by_id = current_user.id
    item.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("نتیجه اعتراض ثبت شد.", "success")
    return redirect(url_for("main.objections"))


@bp.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="شما اجازه دسترسی به این بخش را ندارید."), 403


@bp.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="صفحه یا رکورد موردنظر پیدا نشد."), 404
