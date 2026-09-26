import "dotenv/config";
import { randomBytes, timingSafeEqual } from "node:crypto";
import path from "node:path";
import connectPgSimple from "connect-pg-simple";
import express, { type NextFunction, type Request, type Response } from "express";
import session from "express-session";
import nunjucks from "nunjucks";
import { Pool } from "pg";

import {
  type CurrentUser,
  type FlashCategory,
  courseScore,
  envFlag,
  parseScore,
  toPositiveInt,
  urlFor,
  validNationalId
} from "./domain.js";
import { prisma } from "./prisma.js";
import { hashPassword, verifyPassword } from "./security.js";

const viewsDir = path.resolve(process.cwd(), "school_system/templates");
const staticDir = path.resolve(process.cwd(), "school_system/static");

function addFlash(req: Request, category: FlashCategory, message: string) {
  req.session.flash ??= [];
  req.session.flash.push({ category, message });
}

function takeFlash(req: Request) {
  const items = req.session.flash ?? [];
  req.session.flash = [];
  return items;
}

function isPrismaUniqueError(error: unknown) {
  return Boolean(error && typeof error === "object" && "code" in error && (error as { code?: string }).code === "P2002");
}

function sameToken(expected: string | undefined, received: unknown) {
  if (!expected || typeof received !== "string") return false;
  const a = Buffer.from(expected);
  const b = Buffer.from(received);
  return a.length === b.length && timingSafeEqual(a, b);
}

function formatDate(value: Date) {
  return value.toISOString().slice(0, 16).replace("T", " ");
}

function scoreView<T extends { formative: unknown; final: unknown }>(score: T) {
  const formative = score.formative === null || score.formative === undefined ? null : String(score.formative);
  const finalScore = score.final === null || score.final === undefined ? null : String(score.final);
  return {
    ...score,
    formative,
    final: finalScore,
    course_score: courseScore(formative, finalScore)
  };
}

function objectionView<T extends {
  previous_score: unknown;
  changed_score: unknown;
  score: { formative: unknown; final: unknown };
}>(item: T) {
  return {
    ...item,
    previous_score: item.previous_score === null || item.previous_score === undefined ? null : String(item.previous_score),
    changed_score: item.changed_score === null || item.changed_score === undefined ? null : String(item.changed_score),
    score: scoreView(item.score)
  };
}

async function loadCurrentUser(req: Request): Promise<CurrentUser | undefined> {
  if (!req.session.userId) return undefined;
  const user = await prisma.user.findUnique({
    where: { id: req.session.userId },
    include: { student_profile: true }
  });

  if (!user || !user.is_active_flag) {
    req.session.userId = undefined;
    return undefined;
  }

  return {
    id: user.id,
    national_id: user.national_id,
    username: user.username,
    full_name: user.full_name,
    role: user.role as CurrentUser["role"],
    is_active_flag: user.is_active_flag,
    is_active: user.is_active_flag,
    is_authenticated: true,
    student_profile: user.student_profile
      ? { classroom_id: user.student_profile.classroom_id }
      : null
  };
}

function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (!req.currentUser) {
    addFlash(req, "warning", "برای ادامه وارد سامانه شوید.");
    return res.redirect("/login");
  }
  next();
}

function requireRole(...roles: CurrentUser["role"][]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.currentUser || !roles.includes(req.currentUser.role)) {
      return res.status(403).render("error.html", {
        code: 403,
        message: "شما اجازه دسترسی به این بخش را ندارید."
      });
    }
    next();
  };
}

async function teacherHasAssignment(userId: number, classroomId: number, subjectId: number) {
  return Boolean(
    await prisma.teacherAssignment.findFirst({
      where: { teacher_id: userId, classroom_id: classroomId, subject_id: subjectId },
      select: { id: true }
    })
  );
}

async function canAccessGradebook(user: CurrentUser, classroomId: number, subjectId: number) {
  if (user.role === "admin") return true;
  return user.role === "teacher" && teacherHasAssignment(user.id, classroomId, subjectId);
}

async function isComponentLocked(classroomId: number, subjectId: number, component: "formative" | "final") {
  return Boolean(
    await prisma.gradeLock.findFirst({
      where: { classroom_id: classroomId, subject_id: subjectId, component },
      select: { id: true }
    })
  );
}

async function getClassSubject(classroomId: number, subjectId: number) {
  const [classroom, subject] = await Promise.all([
    prisma.classroom.findUnique({
      where: { id: classroomId },
      include: { grade_level: true }
    }),
    prisma.subject.findUnique({
      where: { id: subjectId },
      include: { grade_level: true }
    })
  ]);

  if (!classroom || !subject || classroom.grade_level_id !== subject.grade_level_id) return null;
  return { classroom, subject };
}

async function studentsInClassroom(classroomId: number) {
  return prisma.user.findMany({
    where: {
      role: "student",
      student_profile: { is: { classroom_id: classroomId } }
    },
    orderBy: { full_name: "asc" }
  });
}

async function announcementsForUser(user: CurrentUser) {
  const clauses: Array<Record<string, unknown>> = [
    { target_type: "all" },
    { target_user_id: user.id }
  ];

  if (user.role === "teacher") {
    clauses.push({ target_type: "teachers" });
  } else if (user.role === "student") {
    clauses.push({ target_type: "students" });
    if (user.student_profile) {
      clauses.push({
        target_type: "class",
        target_classroom_id: user.student_profile.classroom_id
      });
    }
  }

  const items = await prisma.announcement.findMany({
    where: { OR: clauses },
    include: { created_by: true, target_classroom: true, target_user: true },
    orderBy: { created_at: "desc" }
  });

  return items.map((item) => ({
    ...item,
    created_at_display: formatDate(item.created_at)
  }));
}

function redirectBackToGradebook(res: Response, classroomId: number, subjectId: number) {
  return res.redirect(`/gradebook/${classroomId}/${subjectId}`);
}

async function regenerateSession(req: Request) {
  await new Promise<void>((resolve, reject) => {
    req.session.regenerate((error) => (error ? reject(error) : resolve()));
  });
}

export function createApp() {
  const databaseUrl = process.env.DATABASE_URL;
  const sessionSecret = process.env.SESSION_SECRET;
  if (!databaseUrl) throw new Error("DATABASE_URL تنظیم نشده است.");
  if (!sessionSecret || sessionSecret.length < 24) {
    throw new Error("SESSION_SECRET باید تنظیم شود و حداقل ۲۴ نویسه داشته باشد.");
  }

  const app = express();
  const env = nunjucks.configure(viewsDir, {
    autoescape: true,
    express: app,
    noCache: process.env.NODE_ENV !== "production"
  });
  env.addGlobal("url_for", urlFor);

  app.set("view engine", "html");
  app.set("trust proxy", 1);
  app.use("/static", express.static(staticDir));
  app.use(express.urlencoded({ extended: false, limit: "100kb" }));

  const PgStore = connectPgSimple(session);
  const sessionPool = new Pool({ connectionString: databaseUrl });
  app.use(
    session({
      store: new PgStore({
        pool: sessionPool,
        tableName: "user_sessions",
        createTableIfMissing: true
      }),
      name: "school.sid",
      secret: sessionSecret,
      resave: false,
      saveUninitialized: false,
      rolling: true,
      cookie: {
        httpOnly: true,
        sameSite: "lax",
        secure: envFlag(process.env.COOKIE_SECURE, process.env.NODE_ENV === "production"),
        maxAge: 8 * 60 * 60 * 1000
      }
    })
  );

  app.use(async (req, res, next) => {
    try {
      req.session.csrfToken ??= randomBytes(32).toString("base64url");
      req.currentUser = await loadCurrentUser(req);
      res.locals.current_user =
        req.currentUser ??
        {
          is_authenticated: false,
          role: null,
          full_name: ""
        };
      res.locals.csrf_token = () => req.session.csrfToken;
      res.locals.flashes = takeFlash(req);
      next();
    } catch (error) {
      next(error);
    }
  });

  app.use((req, res, next) => {
    if (req.method !== "POST") return next();
    if (!sameToken(req.session.csrfToken, req.body?.csrf_token)) {
      return res.status(403).render("error.html", {
        code: 403,
        message: "درخواست نامعتبر یا منقضی شده است. صفحه را تازه کنید و دوباره تلاش کنید."
      });
    }
    next();
  });

  app.get("/", (req, res) => {
    res.redirect(req.currentUser ? "/dashboard" : "/login");
  });

  app.get("/login", (req, res) => {
    if (req.currentUser) return res.redirect("/dashboard");
    res.render("login.html");
  });

  app.post("/login", async (req, res) => {
    if (req.currentUser) return res.redirect("/dashboard");
    const username = String(req.body?.username ?? "").trim();
    const password = String(req.body?.password ?? "");
    const user = await prisma.user.findUnique({ where: { username } });

    if (!user || !user.is_active_flag || !(await verifyPassword(password, user.password_hash))) {
      addFlash(req, "danger", "نام کاربری یا رمز عبور صحیح نیست.");
      return res.redirect("/login");
    }

    await regenerateSession(req);
    req.session.userId = user.id;
    req.session.csrfToken = randomBytes(32).toString("base64url");
    return res.redirect("/dashboard");
  });

  app.post("/logout", requireAuth, (req, res) => {
    req.session.userId = undefined;
    addFlash(req, "info", "از سامانه خارج شدید.");
    res.redirect("/login");
  });

  app.get("/dashboard", requireAuth, async (req, res) => {
    const user = req.currentUser!;
    let data: Record<string, number> = {};

    if (user.role === "admin") {
      const [teachers, students, classes, pendingObjections] = await Promise.all([
        prisma.user.count({ where: { role: "teacher" } }),
        prisma.user.count({ where: { role: "student" } }),
        prisma.classroom.count(),
        prisma.objection.count({ where: { status: "pending" } })
      ]);
      data = {
        teachers,
        students,
        classes,
        pending_objections: pendingObjections
      };
    } else if (user.role === "teacher") {
      const [assignments, announcements] = await Promise.all([
        prisma.teacherAssignment.count({ where: { teacher_id: user.id } }),
        announcementsForUser(user)
      ]);
      data = { assignments, announcements: announcements.length };
    } else {
      data = { announcements: (await announcementsForUser(user)).length };
    }

    res.render("dashboard.html", { data });
  });

  app.get("/admin/users", requireAuth, requireRole("admin"), async (_req, res) => {
    const [usersRaw, classrooms] = await Promise.all([
      prisma.user.findMany({
        include: {
          student_profile: {
            include: { classroom: true }
          }
        },
        orderBy: [{ role: "asc" }, { full_name: "asc" }]
      }),
      prisma.classroom.findMany({
        include: { grade_level: true },
        orderBy: [{ grade_level: { sort_order: "asc" } }, { name: "asc" }]
      })
    ]);

    const users = usersRaw.map((user) => ({ ...user, is_active: user.is_active_flag }));
    res.render("users.html", { users, classrooms });
  });

  app.post("/admin/users/create", requireAuth, requireRole("admin"), async (req, res) => {
    const nationalId = String(req.body?.national_id ?? "").trim();
    const fullName = String(req.body?.full_name ?? "").trim();
    const role = String(req.body?.role ?? "").trim();
    const classroomId = toPositiveInt(req.body?.classroom_id);

    if (!fullName || !["teacher", "student"].includes(role) || !validNationalId(nationalId)) {
      addFlash(req, "danger", "نام، نقش و کد ملی ۱۰ رقمی معتبر الزامی است.");
      return res.redirect("/admin/users");
    }

    if (role === "student") {
      if (!classroomId || !(await prisma.classroom.findUnique({ where: { id: classroomId } }))) {
        addFlash(req, "danger", "برای دانش‌آموز باید کلاس معتبر انتخاب شود.");
        return res.redirect("/admin/users");
      }
    }

    try {
      const passwordHash = await hashPassword(nationalId);
      await prisma.$transaction(async (tx) => {
        const user = await tx.user.create({
          data: {
            national_id: nationalId,
            username: nationalId,
            full_name: fullName,
            role,
            password_hash: passwordHash
          }
        });
        if (role === "student" && classroomId) {
          await tx.studentProfile.create({
            data: { user_id: user.id, classroom_id: classroomId }
          });
        }
      });
      addFlash(req, "success", "کاربر ایجاد شد. نام کاربری و رمز اولیه همان کد ملی است.");
    } catch (error) {
      if (isPrismaUniqueError(error)) {
        addFlash(req, "danger", "این کد ملی یا نام کاربری قبلاً ثبت شده است.");
      } else {
        throw error;
      }
    }
    res.redirect("/admin/users");
  });

  app.post("/admin/users/:userId/edit", requireAuth, requireRole("admin"), async (req, res) => {
    const userId = toPositiveInt(req.params.userId);
    const fullName = String(req.body?.full_name ?? "").trim();
    const classroomId = toPositiveInt(req.body?.classroom_id);
    const active = req.body?.is_active === "on";

    if (!userId) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });
    const user = await prisma.user.findUnique({
      where: { id: userId },
      include: { student_profile: true }
    });
    if (!user) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });
    if (!fullName) {
      addFlash(req, "danger", "نام نمی‌تواند خالی باشد.");
      return res.redirect("/admin/users");
    }

    if (user.role === "student") {
      if (!classroomId || !(await prisma.classroom.findUnique({ where: { id: classroomId } }))) {
        addFlash(req, "danger", "کلاس معتبر انتخاب کنید.");
        return res.redirect("/admin/users");
      }
      await prisma.$transaction(async (tx) => {
        await tx.user.update({
          where: { id: userId },
          data: { full_name: fullName, is_active_flag: active }
        });
        if (user.student_profile) {
          await tx.studentProfile.update({
            where: { user_id: userId },
            data: { classroom_id: classroomId }
          });
        } else {
          await tx.studentProfile.create({
            data: { user_id: userId, classroom_id: classroomId }
          });
        }
      });
    } else {
      await prisma.user.update({
        where: { id: userId },
        data: { full_name: fullName, is_active_flag: active }
      });
    }

    addFlash(req, "success", "اطلاعات کاربر ویرایش شد.");
    res.redirect("/admin/users");
  });

  app.post("/admin/users/:userId/credentials", requireAuth, requireRole("admin"), async (req, res) => {
    const userId = toPositiveInt(req.params.userId);
    const username = String(req.body?.username ?? "").trim();
    const password = String(req.body?.password ?? "");
    if (!userId) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });
    if (!username || password.length < 6) {
      addFlash(req, "danger", "نام کاربری الزامی و رمز باید حداقل ۶ نویسه باشد.");
      return res.redirect("/admin/users");
    }
    try {
      await prisma.user.update({
        where: { id: userId },
        data: { username, password_hash: await hashPassword(password) }
      });
      addFlash(req, "success", "نام کاربری و رمز عبور توسط مدیر تغییر کرد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) {
        addFlash(req, "danger", "این نام کاربری قبلاً استفاده شده است.");
      } else {
        throw error;
      }
    }
    res.redirect("/admin/users");
  });

  app.post("/admin/users/:userId/reset", requireAuth, requireRole("admin"), async (req, res) => {
    const userId = toPositiveInt(req.params.userId);
    if (!userId) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });
    const user = await prisma.user.findUnique({ where: { id: userId } });
    if (!user) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });

    await prisma.user.update({
      where: { id: userId },
      data: {
        username: user.national_id,
        password_hash: await hashPassword(user.national_id)
      }
    });
    addFlash(req, "success", "نام کاربری و رمز عبور به کد ملی بازنشانی شد.");
    res.redirect("/admin/users");
  });

  app.post("/admin/users/:userId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const userId = toPositiveInt(req.params.userId);
    if (!userId) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });
    const user = await prisma.user.findUnique({ where: { id: userId } });
    if (!user) return res.status(404).render("error.html", { code: 404, message: "کاربر پیدا نشد." });

    if (user.id === req.currentUser!.id || user.role === "admin") {
      addFlash(req, "danger", "حذف این حساب مجاز نیست.");
      return res.redirect("/admin/users");
    }

    await prisma.user.delete({ where: { id: userId } });
    addFlash(req, "success", "کاربر حذف شد.");
    res.redirect("/admin/users");
  });

  app.get("/admin/structure", requireAuth, requireRole("admin"), async (_req, res) => {
    const [grades, classrooms, subjects] = await Promise.all([
      prisma.gradeLevel.findMany({ orderBy: [{ sort_order: "asc" }, { name: "asc" }] }),
      prisma.classroom.findMany({
        include: {
          grade_level: true,
          representative: true,
          students: { include: { user: true } }
        },
        orderBy: [{ grade_level: { sort_order: "asc" } }, { name: "asc" }]
      }),
      prisma.subject.findMany({
        include: { grade_level: true },
        orderBy: [{ grade_level: { sort_order: "asc" } }, { name: "asc" }]
      })
    ]);
    res.render("structure.html", { grades, classrooms, subjects });
  });

  app.post("/admin/grades/create", requireAuth, requireRole("admin"), async (req, res) => {
    const name = String(req.body?.name ?? "").trim();
    const sortOrder = Number.parseInt(String(req.body?.sort_order ?? "0"), 10) || 0;
    if (!name) {
      addFlash(req, "danger", "نام پایه الزامی است.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.gradeLevel.create({ data: { name, sort_order: sortOrder } });
      addFlash(req, "success", "پایه ثبت شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "این پایه قبلاً ثبت شده است.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/grades/:itemId/edit", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    const name = String(req.body?.name ?? "").trim();
    const sortOrder = Number.parseInt(String(req.body?.sort_order ?? "0"), 10) || 0;
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "پایه پیدا نشد." });
    if (!name) {
      addFlash(req, "danger", "نام پایه الزامی است.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.gradeLevel.update({ where: { id: itemId }, data: { name, sort_order: sortOrder } });
      addFlash(req, "success", "پایه ویرایش شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "نام پایه تکراری است.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/grades/:itemId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "پایه پیدا نشد." });
    const [classrooms, subjects] = await Promise.all([
      prisma.classroom.count({ where: { grade_level_id: itemId } }),
      prisma.subject.count({ where: { grade_level_id: itemId } })
    ]);
    if (classrooms || subjects) {
      addFlash(req, "danger", "ابتدا کلاس‌ها و درس‌های این پایه را حذف کنید.");
    } else {
      await prisma.gradeLevel.delete({ where: { id: itemId } });
      addFlash(req, "success", "پایه حذف شد.");
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/classes/create", requireAuth, requireRole("admin"), async (req, res) => {
    const name = String(req.body?.name ?? "").trim();
    const gradeId = toPositiveInt(req.body?.grade_level_id);
    if (!name || !gradeId || !(await prisma.gradeLevel.findUnique({ where: { id: gradeId } }))) {
      addFlash(req, "danger", "نام کلاس و پایه معتبر الزامی است.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.classroom.create({ data: { name, grade_level_id: gradeId } });
      addFlash(req, "success", "کلاس ثبت شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "این کلاس در پایه انتخاب‌شده قبلاً وجود دارد.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/classes/:itemId/edit", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    const name = String(req.body?.name ?? "").trim();
    const gradeId = toPositiveInt(req.body?.grade_level_id);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "کلاس پیدا نشد." });
    const item = await prisma.classroom.findUnique({ where: { id: itemId } });
    if (!item || !name || !gradeId || !(await prisma.gradeLevel.findUnique({ where: { id: gradeId } }))) {
      addFlash(req, "danger", "اطلاعات کلاس معتبر نیست.");
      return res.redirect("/admin/structure");
    }
    if (
      gradeId !== item.grade_level_id &&
      (await prisma.studentProfile.count({ where: { classroom_id: itemId } })) > 0
    ) {
      addFlash(req, "danger", "تا زمانی که دانش‌آموز در کلاس است، پایه کلاس قابل تغییر نیست.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.classroom.update({ where: { id: itemId }, data: { name, grade_level_id: gradeId } });
      addFlash(req, "success", "کلاس ویرایش شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "نام کلاس تکراری است.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/classes/:itemId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "کلاس پیدا نشد." });
    if ((await prisma.studentProfile.count({ where: { classroom_id: itemId } })) > 0) {
      addFlash(req, "danger", "کلاس دارای دانش‌آموز است و قابل حذف نیست.");
    } else {
      await prisma.classroom.delete({ where: { id: itemId } });
      addFlash(req, "success", "کلاس حذف شد.");
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/subjects/create", requireAuth, requireRole("admin"), async (req, res) => {
    const name = String(req.body?.name ?? "").trim();
    const gradeId = toPositiveInt(req.body?.grade_level_id);
    if (!name || !gradeId || !(await prisma.gradeLevel.findUnique({ where: { id: gradeId } }))) {
      addFlash(req, "danger", "نام درس و پایه معتبر الزامی است.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.subject.create({ data: { name, grade_level_id: gradeId } });
      addFlash(req, "success", "درس ثبت شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "این درس در پایه انتخاب‌شده قبلاً وجود دارد.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/subjects/:itemId/edit", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    const name = String(req.body?.name ?? "").trim();
    const gradeId = toPositiveInt(req.body?.grade_level_id);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "درس پیدا نشد." });
    const item = await prisma.subject.findUnique({ where: { id: itemId } });
    if (!item || !name || !gradeId || !(await prisma.gradeLevel.findUnique({ where: { id: gradeId } }))) {
      addFlash(req, "danger", "اطلاعات درس معتبر نیست.");
      return res.redirect("/admin/structure");
    }
    if (
      gradeId !== item.grade_level_id &&
      (await prisma.teacherAssignment.count({ where: { subject_id: itemId } })) > 0
    ) {
      addFlash(req, "danger", "درس تخصیص داده شده است؛ پایه آن قابل تغییر نیست.");
      return res.redirect("/admin/structure");
    }
    try {
      await prisma.subject.update({ where: { id: itemId }, data: { name, grade_level_id: gradeId } });
      addFlash(req, "success", "درس ویرایش شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "نام درس تکراری است.");
      else throw error;
    }
    res.redirect("/admin/structure");
  });

  app.post("/admin/subjects/:itemId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "درس پیدا نشد." });
    const [assignments, scores] = await Promise.all([
      prisma.teacherAssignment.count({ where: { subject_id: itemId } }),
      prisma.score.count({ where: { subject_id: itemId } })
    ]);
    if (assignments || scores) {
      addFlash(req, "danger", "این درس دارای تخصیص یا نمره است و قابل حذف نیست.");
    } else {
      await prisma.subject.delete({ where: { id: itemId } });
      addFlash(req, "success", "درس حذف شد.");
    }
    res.redirect("/admin/structure");
  });

  app.get("/admin/assignments", requireAuth, requireRole("admin"), async (_req, res) => {
    const [assignments, teachers, classrooms, subjects] = await Promise.all([
      prisma.teacherAssignment.findMany({
        include: {
          teacher: true,
          classroom: { include: { grade_level: true } },
          subject: { include: { grade_level: true } }
        },
        orderBy: { id: "desc" }
      }),
      prisma.user.findMany({
        where: { role: "teacher", is_active_flag: true },
        orderBy: { full_name: "asc" }
      }),
      prisma.classroom.findMany({
        include: { grade_level: true },
        orderBy: [{ grade_level: { sort_order: "asc" } }, { name: "asc" }]
      }),
      prisma.subject.findMany({
        include: { grade_level: true },
        orderBy: [{ grade_level: { sort_order: "asc" } }, { name: "asc" }]
      })
    ]);

    res.render("assignments.html", { assignments, teachers, classrooms, subjects });
  });

  app.post("/admin/assignments/create", requireAuth, requireRole("admin"), async (req, res) => {
    const teacherId = toPositiveInt(req.body?.teacher_id);
    const classroomId = toPositiveInt(req.body?.classroom_id);
    const subjectId = toPositiveInt(req.body?.subject_id);
    if (!teacherId || !classroomId || !subjectId) {
      addFlash(req, "danger", "معلم، کلاس و درس معتبر انتخاب کنید.");
      return res.redirect("/admin/assignments");
    }
    const [teacher, pair] = await Promise.all([
      prisma.user.findUnique({ where: { id: teacherId } }),
      getClassSubject(classroomId, subjectId)
    ]);
    if (!teacher || teacher.role !== "teacher") {
      addFlash(req, "danger", "معلم معتبر انتخاب کنید.");
      return res.redirect("/admin/assignments");
    }
    if (!pair) {
      addFlash(req, "danger", "درس باید متعلق به پایه همان کلاس باشد.");
      return res.redirect("/admin/assignments");
    }

    try {
      await prisma.teacherAssignment.create({
        data: { teacher_id: teacherId, classroom_id: classroomId, subject_id: subjectId }
      });
      addFlash(req, "success", "معلم و درس به کلاس تخصیص داده شد.");
    } catch (error) {
      if (isPrismaUniqueError(error)) addFlash(req, "danger", "این تخصیص قبلاً ثبت شده است.");
      else throw error;
    }
    res.redirect("/admin/assignments");
  });

  app.post("/admin/assignments/:itemId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "تخصیص پیدا نشد." });
    await prisma.teacherAssignment.delete({ where: { id: itemId } });
    addFlash(req, "success", "تخصیص حذف شد.");
    res.redirect("/admin/assignments");
  });

  app.post("/admin/classes/:classroomId/representative", requireAuth, requireRole("admin"), async (req, res) => {
    const classroomId = toPositiveInt(req.params.classroomId);
    const studentId = toPositiveInt(req.body?.student_id);
    if (!classroomId || !(await prisma.classroom.findUnique({ where: { id: classroomId } }))) {
      return res.status(404).render("error.html", { code: 404, message: "کلاس پیدا نشد." });
    }

    if (!studentId) {
      await prisma.classroom.update({
        where: { id: classroomId },
        data: { representative_student_id: null }
      });
      addFlash(req, "success", "نماینده کلاس حذف شد.");
      return res.redirect("/admin/structure");
    }

    const student = await prisma.user.findUnique({
      where: { id: studentId },
      include: { student_profile: true }
    });
    if (!student || student.role !== "student" || student.student_profile?.classroom_id !== classroomId) {
      addFlash(req, "danger", "دانش‌آموز انتخاب‌شده عضو این کلاس نیست.");
      return res.redirect("/admin/structure");
    }

    await prisma.classroom.update({
      where: { id: classroomId },
      data: { representative_student_id: studentId }
    });
    addFlash(req, "success", "نماینده کلاس ثبت شد.");
    res.redirect("/admin/structure");
  });

  app.get("/announcements", requireAuth, async (req, res) => {
    const user = req.currentUser!;
    if (user.role === "admin") {
      const [items, classrooms, users] = await Promise.all([
        prisma.announcement.findMany({
          include: { created_by: true, target_classroom: true, target_user: true },
          orderBy: { created_at: "desc" }
        }),
        prisma.classroom.findMany({
          include: { grade_level: true },
          orderBy: { name: "asc" }
        }),
        prisma.user.findMany({
          where: { role: { in: ["teacher", "student"] } },
          orderBy: { full_name: "asc" }
        })
      ]);
      const announcements = items.map((item) => ({
        ...item,
        created_at_display: formatDate(item.created_at)
      }));
      return res.render("announcements.html", { announcements, classrooms, users });
    }

    res.render("announcements.html", {
      announcements: await announcementsForUser(user),
      classrooms: [],
      users: []
    });
  });

  app.post("/admin/announcements/create", requireAuth, requireRole("admin"), async (req, res) => {
    const title = String(req.body?.title ?? "").trim();
    const body = String(req.body?.body ?? "").trim();
    const targetType = String(req.body?.target_type ?? "").trim();
    const classroomId = toPositiveInt(req.body?.target_classroom_id);
    const userId = toPositiveInt(req.body?.target_user_id);

    if (!title || !body || !["all", "teachers", "students", "class", "user"].includes(targetType)) {
      addFlash(req, "danger", "عنوان، متن و نوع مخاطب معتبر الزامی است.");
      return res.redirect("/announcements");
    }
    if (targetType === "class" && (!classroomId || !(await prisma.classroom.findUnique({ where: { id: classroomId } })))) {
      addFlash(req, "danger", "کلاس مخاطب معتبر نیست.");
      return res.redirect("/announcements");
    }
    if (targetType === "user" && (!userId || !(await prisma.user.findUnique({ where: { id: userId } })))) {
      addFlash(req, "danger", "کاربر مخاطب معتبر نیست.");
      return res.redirect("/announcements");
    }

    await prisma.announcement.create({
      data: {
        title,
        body,
        target_type: targetType,
        target_classroom_id: targetType === "class" ? classroomId : null,
        target_user_id: targetType === "user" ? userId : null,
        created_by_id: req.currentUser!.id
      }
    });
    addFlash(req, "success", "اطلاعیه ارسال شد.");
    res.redirect("/announcements");
  });

  app.post("/admin/announcements/:itemId/delete", requireAuth, requireRole("admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "اطلاعیه پیدا نشد." });
    await prisma.announcement.delete({ where: { id: itemId } });
    addFlash(req, "success", "اطلاعیه حذف شد.");
    res.redirect("/announcements");
  });

  app.get("/gradebooks", requireAuth, async (req, res) => {
    const user = req.currentUser!;
    if (user.role === "admin") {
      const [assignments, classrooms, subjects] = await Promise.all([
        prisma.teacherAssignment.findMany({
          include: {
            teacher: true,
            classroom: { include: { grade_level: true } },
            subject: true
          },
          orderBy: [{ classroom_id: "asc" }, { subject_id: "asc" }]
        }),
        prisma.classroom.findMany({
          include: { grade_level: true },
          orderBy: { name: "asc" }
        }),
        prisma.subject.findMany({ orderBy: { name: "asc" } })
      ]);
      const pairs = classrooms.flatMap((classroom) =>
        subjects
          .filter((subject) => subject.grade_level_id === classroom.grade_level_id)
          .map((subject) => ({ classroom, subject }))
      );
      return res.render("gradebooks.html", { assignments, pairs });
    }

    if (user.role === "teacher") {
      const assignments = await prisma.teacherAssignment.findMany({
        where: { teacher_id: user.id },
        include: {
          classroom: { include: { grade_level: true } },
          subject: true
        },
        orderBy: { classroom_id: "asc" }
      });
      return res.render("gradebooks.html", { assignments, pairs: [] });
    }

    res.redirect("/student/report");
  });

  app.all("/gradebook/:classroomId/:subjectId", requireAuth, async (req, res) => {
    const classroomId = toPositiveInt(req.params.classroomId);
    const subjectId = toPositiveInt(req.params.subjectId);
    if (!classroomId || !subjectId) {
      return res.status(404).render("error.html", { code: 404, message: "کلاس یا درس پیدا نشد." });
    }

    const pair = await getClassSubject(classroomId, subjectId);
    if (!pair) return res.status(404).render("error.html", { code: 404, message: "کلاس یا درس پیدا نشد." });
    const user = req.currentUser!;
    if (!(await canAccessGradebook(user, classroomId, subjectId))) {
      return res.status(403).render("error.html", {
        code: 403,
        message: "شما اجازه دسترسی به این دفتر نمره را ندارید."
      });
    }

    const students = await studentsInClassroom(classroomId);
    const [formativeLocked, finalLocked] = await Promise.all([
      isComponentLocked(classroomId, subjectId, "formative"),
      isComponentLocked(classroomId, subjectId, "final")
    ]);

    if (req.method === "POST") {
      const action = String(req.body?.action ?? "save");
      const teacherActions = new Set(["save", "finalize_formative", "finalize_final"]);
      const adminActions = new Set([
        "save",
        "lock_formative",
        "lock_final",
        "lock_both",
        "unlock_formative",
        "unlock_final",
        "unlock_both"
      ]);
      if (user.role === "teacher" && !teacherActions.has(action)) {
        return res.status(403).render("error.html", { code: 403, message: "این عملیات برای معلم مجاز نیست." });
      }
      if (user.role === "admin" && !adminActions.has(action)) {
        return res.status(403).render("error.html", { code: 403, message: "عملیات نامعتبر است." });
      }
      if (!["admin", "teacher"].includes(user.role)) {
        return res.status(403).render("error.html", { code: 403, message: "دسترسی مجاز نیست." });
      }

      if (action === "save") {
        try {
          await prisma.$transaction(async (tx) => {
            for (const student of students) {
              const where = {
                student_id_classroom_id_subject_id: {
                  student_id: student.id,
                  classroom_id: classroomId,
                  subject_id: subjectId
                }
              };
              const existing = await tx.score.findUnique({ where });
              const formative = formativeLocked
                ? existing?.formative ?? null
                : parseScore(req.body?.[`formative_${student.id}`]);
              const finalScore = finalLocked
                ? existing?.final ?? null
                : parseScore(req.body?.[`final_${student.id}`]);

              await tx.score.upsert({
                where,
                create: {
                  student_id: student.id,
                  classroom_id: classroomId,
                  subject_id: subjectId,
                  formative,
                  final: finalScore,
                  updated_by_id: user.id
                },
                update: {
                  ...(formativeLocked ? {} : { formative }),
                  ...(finalLocked ? {} : { final: finalScore }),
                  updated_by_id: user.id,
                  updated_at: new Date()
                }
              });
            }
          });
          addFlash(req, "success", "نمرات به صورت موقت ذخیره شدند.");
        } catch (error) {
          if (error instanceof Error && error.message.startsWith("نمره")) {
            addFlash(req, "danger", error.message);
          } else {
            throw error;
          }
        }
        return redirectBackToGradebook(res, classroomId, subjectId);
      }

      const lockComponents: Array<"formative" | "final"> = [];
      const unlockComponents: Array<"formative" | "final"> = [];
      if (["finalize_formative", "lock_formative"].includes(action)) lockComponents.push("formative");
      else if (["finalize_final", "lock_final"].includes(action)) lockComponents.push("final");
      else if (action === "lock_both") lockComponents.push("formative", "final");
      else if (action === "unlock_formative") unlockComponents.push("formative");
      else if (action === "unlock_final") unlockComponents.push("final");
      else if (action === "unlock_both") unlockComponents.push("formative", "final");
      else return res.status(400).render("error.html", { code: 400, message: "عملیات نامعتبر است." });

      if (unlockComponents.length && user.role !== "admin") {
        return res.status(403).render("error.html", { code: 403, message: "فقط مدیر می‌تواند قفل نمرات را باز کند." });
      }

      if (action === "finalize_formative" || action === "finalize_final") {
        const component: "formative" | "final" =
          action === "finalize_formative" ? "formative" : "final";
        if (await isComponentLocked(classroomId, subjectId, component)) {
          addFlash(req, "danger", "این بخش از نمرات قبلاً قفل شده است و فقط مدیر می‌تواند آن را بازگشایی کند.");
          return redirectBackToGradebook(res, classroomId, subjectId);
        }

        try {
          await prisma.$transaction(async (tx) => {
            for (const student of students) {
              const value = parseScore(req.body?.[`${component}_${student.id}`]);
              const where = {
                student_id_classroom_id_subject_id: {
                  student_id: student.id,
                  classroom_id: classroomId,
                  subject_id: subjectId
                }
              };
              await tx.score.upsert({
                where,
                create: {
                  student_id: student.id,
                  classroom_id: classroomId,
                  subject_id: subjectId,
                  ...(component === "formative" ? { formative: value } : { final: value }),
                  updated_by_id: user.id
                },
                update: {
                  ...(component === "formative" ? { formative: value } : { final: value }),
                  updated_by_id: user.id,
                  updated_at: new Date()
                }
              });
            }

            await tx.gradeLock.upsert({
              where: {
                classroom_id_subject_id_component: {
                  classroom_id: classroomId,
                  subject_id: subjectId,
                  component
                }
              },
              create: {
                classroom_id: classroomId,
                subject_id: subjectId,
                component,
                locked_by_id: user.id
              },
              update: {
                locked_by_id: user.id,
                locked_at: new Date()
              }
            });
          });
          addFlash(req, "success", "نمرات ذخیره و بخش موردنظر نهایی شد.");
        } catch (error) {
          if (error instanceof Error && error.message.startsWith("نمره")) {
            addFlash(req, "danger", error.message);
          } else {
            throw error;
          }
        }
        return redirectBackToGradebook(res, classroomId, subjectId);
      }

      await prisma.$transaction(async (tx) => {
        for (const component of lockComponents) {
          await tx.gradeLock.upsert({
            where: {
              classroom_id_subject_id_component: {
                classroom_id: classroomId,
                subject_id: subjectId,
                component
              }
            },
            create: {
              classroom_id: classroomId,
              subject_id: subjectId,
              component,
              locked_by_id: user.id
            },
            update: {
              locked_by_id: user.id,
              locked_at: new Date()
            }
          });
        }
        if (unlockComponents.length) {
          await tx.gradeLock.deleteMany({
            where: {
              classroom_id: classroomId,
              subject_id: subjectId,
              component: { in: unlockComponents }
            }
          });
        }
      });
      addFlash(req, "success", "وضعیت قفل نمرات به‌روزرسانی شد.");
      return redirectBackToGradebook(res, classroomId, subjectId);
    }

    const scores = await prisma.score.findMany({
      where: { classroom_id: classroomId, subject_id: subjectId }
    });
    const scoreMap = Object.fromEntries(
      scores.map((score) => [String(score.student_id), scoreView(score)])
    );
    res.render("gradebook.html", {
      classroom: pair.classroom,
      subject: pair.subject,
      students,
      score_map: scoreMap,
      formative_locked: formativeLocked,
      final_locked: finalLocked
    });
  });

  app.get("/student/report", requireAuth, requireRole("student"), async (req, res) => {
    const user = req.currentUser!;
    const classroomId = user.student_profile?.classroom_id;
    if (!classroomId) {
      return res.status(404).render("error.html", { code: 404, message: "کلاس دانش‌آموز مشخص نشده است." });
    }
    const [classroom, scoresRaw] = await Promise.all([
      prisma.classroom.findUnique({
        where: { id: classroomId },
        include: { grade_level: true }
      }),
      prisma.score.findMany({
        where: { student_id: user.id, classroom_id: classroomId },
        include: { subject: true },
        orderBy: { subject_id: "asc" }
      })
    ]);
    if (!classroom) return res.status(404).render("error.html", { code: 404, message: "کلاس پیدا نشد." });
    res.render("student_report.html", {
      scores: scoresRaw.map(scoreView),
      classroom
    });
  });

  app.get("/student/teachers", requireAuth, requireRole("student"), async (req, res) => {
    const user = req.currentUser!;
    const classroomId = user.student_profile?.classroom_id;
    if (!classroomId) {
      return res.status(404).render("error.html", { code: 404, message: "کلاس دانش‌آموز مشخص نشده است." });
    }
    const [classroom, assignments] = await Promise.all([
      prisma.classroom.findUnique({
        where: { id: classroomId },
        include: { grade_level: true }
      }),
      prisma.teacherAssignment.findMany({
        where: { classroom_id: classroomId },
        include: { teacher: true, subject: true },
        orderBy: { subject_id: "asc" }
      })
    ]);
    if (!classroom) return res.status(404).render("error.html", { code: 404, message: "کلاس پیدا نشد." });
    res.render("student_teachers.html", { assignments, classroom });
  });

  app.get("/objections", requireAuth, async (req, res) => {
    const user = req.currentUser!;
    const include = {
      student: true,
      score: {
        include: {
          subject: true,
          classroom: true
        }
      }
    } as const;

    if (user.role === "student") {
      const classroomId = user.student_profile?.classroom_id;
      const [itemsRaw, scoresRaw] = await Promise.all([
        prisma.objection.findMany({
          where: { student_id: user.id },
          include,
          orderBy: { created_at: "desc" }
        }),
        classroomId
          ? prisma.score.findMany({
              where: { student_id: user.id, classroom_id: classroomId },
              include: { subject: true },
              orderBy: { subject_id: "asc" }
            })
          : Promise.resolve([])
      ]);
      return res.render("objections.html", {
        objections: itemsRaw.map(objectionView),
        scores: scoresRaw.map(scoreView)
      });
    }

    let itemsRaw = await prisma.objection.findMany({
      include,
      orderBy: { created_at: "desc" }
    });

    if (user.role === "teacher") {
      const assignments = await prisma.teacherAssignment.findMany({
        where: { teacher_id: user.id },
        select: { classroom_id: true, subject_id: true }
      });
      const allowed = new Set(assignments.map((a) => `${a.classroom_id}:${a.subject_id}`));
      itemsRaw = itemsRaw.filter((item) =>
        allowed.has(`${item.score.classroom_id}:${item.score.subject_id}`)
      );
    }

    res.render("objections.html", {
      objections: itemsRaw.map(objectionView),
      scores: []
    });
  });

  app.post("/student/objections/create", requireAuth, requireRole("student"), async (req, res) => {
    const scoreId = toPositiveInt(req.body?.score_id);
    const component = String(req.body?.component ?? "").trim();
    const reason = String(req.body?.reason ?? "").trim();
    const score = scoreId
      ? await prisma.score.findUnique({ where: { id: scoreId } })
      : null;

    if (
      !score ||
      score.student_id !== req.currentUser!.id ||
      !["formative", "final"].includes(component) ||
      !reason
    ) {
      addFlash(req, "danger", "اطلاعات اعتراض کامل یا معتبر نیست.");
      return res.redirect("/objections");
    }
    const selectedValue = component === "formative" ? score.formative : score.final;
    if (selectedValue === null) {
      addFlash(req, "danger", "برای بخشی که هنوز نمره ندارد امکان اعتراض وجود ندارد.");
      return res.redirect("/objections");
    }

    const duplicate = await prisma.objection.findFirst({
      where: {
        student_id: req.currentUser!.id,
        score_id: score.id,
        component,
        status: "pending"
      }
    });
    if (duplicate) {
      addFlash(req, "warning", "برای این نمره یک اعتراض در حال بررسی دارید.");
      return res.redirect("/objections");
    }

    await prisma.objection.create({
      data: {
        student_id: req.currentUser!.id,
        score_id: score.id,
        component,
        reason
      }
    });
    addFlash(req, "success", "اعتراض ثبت شد.");
    res.redirect("/objections");
  });

  app.post("/objections/:itemId/resolve", requireAuth, requireRole("teacher", "admin"), async (req, res) => {
    const itemId = toPositiveInt(req.params.itemId);
    if (!itemId) return res.status(404).render("error.html", { code: 404, message: "اعتراض پیدا نشد." });

    const item = await prisma.objection.findUnique({
      where: { id: itemId },
      include: { score: true }
    });
    if (!item) return res.status(404).render("error.html", { code: 404, message: "اعتراض پیدا نشد." });
    if (item.status !== "pending") {
      addFlash(req, "warning", "این اعتراض قبلاً بررسی شده است.");
      return res.redirect("/objections");
    }

    const user = req.currentUser!;
    if (
      user.role === "teacher" &&
      !(await teacherHasAssignment(user.id, item.score.classroom_id, item.score.subject_id))
    ) {
      return res.status(403).render("error.html", { code: 403, message: "این اعتراض مربوط به کلاس شما نیست." });
    }

    const decision = String(req.body?.decision ?? "");
    const response = String(req.body?.response ?? "").trim();

    if (decision === "reject") {
      if (!response) {
        addFlash(req, "danger", "برای رد اعتراض، علت رد الزامی است.");
        return res.redirect("/objections");
      }
      await prisma.objection.update({
        where: { id: item.id },
        data: {
          status: "rejected",
          response,
          resolved_by_id: user.id,
          resolved_at: new Date()
        }
      });
    } else if (decision === "approve") {
      const component = item.component === "formative" ? "formative" : "final";
      if (await isComponentLocked(item.score.classroom_id, item.score.subject_id, component)) {
        addFlash(req, "danger", "این بخش از نمرات قفل است؛ مدیر باید ابتدا آن را بازگشایی کند.");
        return res.redirect("/objections");
      }

      let newScore: string | null;
      try {
        newScore = parseScore(req.body?.new_score);
      } catch (error) {
        addFlash(req, "danger", error instanceof Error ? error.message : "نمره معتبر نیست.");
        return res.redirect("/objections");
      }
      if (newScore === null) {
        addFlash(req, "danger", "در صورت تأیید اعتراض، ثبت نمره جدید الزامی است.");
        return res.redirect("/objections");
      }

      const previousScore = component === "formative" ? item.score.formative : item.score.final;
      await prisma.$transaction([
        prisma.score.update({
          where: { id: item.score.id },
          data: {
            ...(component === "formative" ? { formative: newScore } : { final: newScore }),
            updated_by_id: user.id,
            updated_at: new Date()
          }
        }),
        prisma.objection.update({
          where: { id: item.id },
          data: {
            previous_score: previousScore,
            changed_score: newScore,
            status: "approved",
            response: response || "اعتراض تأیید و نمره اصلاح شد.",
            resolved_by_id: user.id,
            resolved_at: new Date()
          }
        })
      ]);
    } else {
      return res.status(400).render("error.html", { code: 400, message: "تصمیم نامعتبر است." });
    }

    addFlash(req, "success", "نتیجه اعتراض ثبت شد.");
    res.redirect("/objections");
  });

  app.use((_req, res) => {
    res.status(404).render("error.html", {
      code: 404,
      message: "صفحه یا رکورد موردنظر پیدا نشد."
    });
  });

  app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
    console.error(error);
    if (res.headersSent) return;
    res.status(500).render("error.html", {
      code: 500,
      message: "خطای داخلی رخ داد. لطفاً دوباره تلاش کنید."
    });
  });

  return app;
}

export async function ensureInitialAdmin() {
  if (await prisma.user.findFirst({ where: { role: "admin" }, select: { id: true } })) return;

  const nationalId = String(process.env.ADMIN_NATIONAL_ID ?? "").trim();
  const fullName = String(process.env.ADMIN_FULL_NAME ?? "مدیر سامانه").trim();
  if (!validNationalId(nationalId)) {
    console.warn("ADMIN_NATIONAL_ID تنظیم نشده یا معتبر نیست؛ مدیر اولیه ساخته نشد.");
    return;
  }

  try {
    await prisma.user.create({
      data: {
        national_id: nationalId,
        username: nationalId,
        password_hash: await hashPassword(nationalId),
        full_name: fullName || "مدیر سامانه",
        role: "admin"
      }
    });
    console.log("Initial admin account created.");
  } catch (error) {
    if (!isPrismaUniqueError(error)) throw error;
  }
}
