export type Role = "admin" | "teacher" | "student";

export type FlashCategory = "success" | "danger" | "warning" | "info";

export interface FlashMessage {
  category: FlashCategory;
  message: string;
}

export interface CurrentUser {
  id: number;
  national_id: string;
  username: string;
  full_name: string;
  role: Role;
  is_active_flag: boolean;
  is_active: boolean;
  is_authenticated: boolean;
  student_profile: {
    classroom_id: number;
  } | null;
}

export function validNationalId(value: unknown): boolean {
  return /^\d{10}$/.test(String(value ?? "").trim());
}

export function parseScore(value: unknown): string | null {
  const raw = String(value ?? "").trim();
  if (raw === "") return null;
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) {
    throw new Error("نمره باید عدد باشد.");
  }
  if (numeric < 0 || numeric > 20) {
    throw new Error("نمره باید بین ۰ تا ۲۰ باشد.");
  }
  return numeric.toFixed(2);
}

export function courseScore(formative: unknown, finalScore: unknown): string | null {
  if (formative === null || formative === undefined || finalScore === null || finalScore === undefined) {
    return null;
  }
  const result = (Number(formative) + Number(finalScore)) / 2;
  return result.toFixed(2);
}

export function toPositiveInt(value: unknown): number | null {
  const n = Number.parseInt(String(value ?? ""), 10);
  return Number.isInteger(n) && n > 0 ? n : null;
}

export function envFlag(value: string | undefined, fallback = false): boolean {
  if (value === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(value.toLowerCase());
}

type Kwargs = Record<string, unknown> & { __keywords?: boolean };

export function urlFor(endpoint: string, kwargs: Kwargs = {}): string {
  const id = (name: string) => encodeURIComponent(String(kwargs[name] ?? ""));
  const routes: Record<string, () => string> = {
    "static": () => `/static/${id("filename")}`,
    "main.index": () => "/",
    "main.login": () => "/login",
    "main.logout": () => "/logout",
    "main.dashboard": () => "/dashboard",
    "main.admin_users": () => "/admin/users",
    "main.admin_user_create": () => "/admin/users/create",
    "main.admin_user_edit": () => `/admin/users/${id("user_id")}/edit`,
    "main.admin_user_credentials": () => `/admin/users/${id("user_id")}/credentials`,
    "main.admin_user_reset": () => `/admin/users/${id("user_id")}/reset`,
    "main.admin_user_delete": () => `/admin/users/${id("user_id")}/delete`,
    "main.admin_structure": () => "/admin/structure",
    "main.admin_grade_create": () => "/admin/grades/create",
    "main.admin_grade_edit": () => `/admin/grades/${id("item_id")}/edit`,
    "main.admin_grade_delete": () => `/admin/grades/${id("item_id")}/delete`,
    "main.admin_class_create": () => "/admin/classes/create",
    "main.admin_class_edit": () => `/admin/classes/${id("item_id")}/edit`,
    "main.admin_class_delete": () => `/admin/classes/${id("item_id")}/delete`,
    "main.admin_subject_create": () => "/admin/subjects/create",
    "main.admin_subject_edit": () => `/admin/subjects/${id("item_id")}/edit`,
    "main.admin_subject_delete": () => `/admin/subjects/${id("item_id")}/delete`,
    "main.admin_assignments": () => "/admin/assignments",
    "main.admin_assignment_create": () => "/admin/assignments/create",
    "main.admin_assignment_delete": () => `/admin/assignments/${id("item_id")}/delete`,
    "main.admin_set_representative": () => `/admin/classes/${id("classroom_id")}/representative`,
    "main.announcements": () => "/announcements",
    "main.admin_announcement_create": () => "/admin/announcements/create",
    "main.admin_announcement_delete": () => `/admin/announcements/${id("item_id")}/delete`,
    "main.gradebooks": () => "/gradebooks",
    "main.gradebook": () => `/gradebook/${id("classroom_id")}/${id("subject_id")}`,
    "main.student_report": () => "/student/report",
    "main.student_teachers": () => "/student/teachers",
    "main.objections": () => "/objections",
    "main.student_objection_create": () => "/student/objections/create",
    "main.objection_resolve": () => `/objections/${id("item_id")}/resolve`
  };

  const builder = routes[endpoint];
  if (!builder) {
    throw new Error(`Unknown route endpoint: ${endpoint}`);
  }
  return builder();
}
