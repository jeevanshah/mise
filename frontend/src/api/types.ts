// Mirrors app/api/schemas/*.py and app/models/*.py enums exactly. Kept as
// one file since the backend's own schema surface is the single source of
// truth here — see frontend/README.md for the "no client-side model of
// truth beyond this mirror" rule.

// ---- Enums (string literal unions — mirrors each Python str Enum) ----

export type MembershipRole = "owner" | "ops_manager" | "head_chef" | "sous_chef" | "line_staff"

export const MANAGEMENT_ROLES: MembershipRole[] = ["owner", "ops_manager", "head_chef"]
export const PREP_EXECUTION_ROLES: MembershipRole[] = ["head_chef", "sous_chef"]

export type AttendanceStatus = "present" | "late" | "absent" | "sick"
export type AttendanceSource = "chef" | "staff_link"

export type CaptureType = "restock" | "eighty_six" | "equipment_issue" | "unparsed"
export type MatchedEntityType = "ingredient" | "menu_item" | "equipment_item"
export type CaptureStatus = "proposed" | "confirmed" | "rejected"

export type EquipmentStatus = "active" | "inactive"
export type EquipmentIssuePriority = "low" | "medium" | "high"
export type EquipmentIssueStatus = "open" | "resolved"

export type MenuAvailabilityStatus = "available" | "low" | "unavailable"

export type PrepTaskStatus = "not_started" | "in_progress" | "done" | "blocked"

export type PurchaseOrderStatus = "draft" | "sending" | "sent" | "send_failed"
export type DeliveryStatus = "pending" | "received" | "partially_received"
export type DeliveryIssueType = "short_delivery" | "damaged" | "wrong_item" | "late" | "quality" | "other"

export type ShiftStatus = "draft" | "published" | "cancelled"
export type StaffResponseStatus = "pending" | "confirmed" | "declined"

export type ServiceDayStatus = "planned" | "open" | "closed"

// ---- Auth (Epic 1 step 4) ----

export interface MagicLinkRequestResponse {
  detail: string
  dev_token: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface MembershipOut {
  venue_id: string
  role: MembershipRole
}

export interface MeResponse {
  id: string
  email: string
  is_active: boolean
  memberships: MembershipOut[]
}

// ---- Onboarding (Epic 1 step 5) ----

export interface OrganisationOut {
  id: string
  name: string
}

export interface VenueOut {
  id: string
  organisation_id: string
  name: string
  timezone: string
  business_day_boundary: string
}

export interface OrganisationCreateResponse {
  organisation: OrganisationOut
  venue: VenueOut
  membership: MembershipOut
}

export interface InviteUserResponse {
  user_id: string
  email: string
  venue_id: string
  role: MembershipRole
}

// ---- Staffing (Epic 1 step 6) ----

export interface StationOut {
  id: string
  venue_id: string
  name: string
}

export interface StaffOut {
  id: string
  venue_id: string
  name: string
  user_id: string | null
  contact_email: string | null
}

export interface StaffSkillOut {
  id: string
  staff_id: string
  station_id: string
  trained: boolean
}

export interface StaffDetailOut extends StaffOut {
  skills: StaffSkillOut[]
}

export interface CoverageRuleOut {
  id: string
  venue_id: string
  station_id: string
  day_of_week: number
  window_start: string
  window_end: string
  minimum_staff: number
}

// ---- Catalog (Epic 1 step 7) ----

export interface SupplierOut {
  id: string
  venue_id: string
  name: string
  contact_email: string | null
  order_days: string | null
  cutoff_time: string | null
  notes: string | null
}

export interface IngredientOut {
  id: string
  venue_id: string
  name: string
  unit: string
  ordering_unit: string
  preferred_supplier_id: string | null
}

export interface MenuItemOut {
  id: string
  venue_id: string
  name: string
}

export interface EquipmentItemOut {
  id: string
  venue_id: string
  name: string
  location: string | null
  repair_contact: string | null
  status: EquipmentStatus
}

// ---- Service days (Epic 1 step 8) ----

export interface ServiceDayOut {
  id: string
  venue_id: string
  business_date: string
  status: ServiceDayStatus
  opened_at: string | null
  closed_at: string | null
}

// ---- Roster (Epic 2) ----

export interface StaffResponseOut {
  id: string
  status: StaffResponseStatus
  responded_at: string | null
  responded_via: string | null
}

export interface ShiftOut {
  id: string
  venue_id: string
  service_day_id: string
  station_id: string
  staff_id: string
  start_at: string
  end_at: string
  status: ShiftStatus
  response: StaffResponseOut | null
}

export interface PublishResultOut {
  shift: ShiftOut
  dev_staff_link_token: string | null
}

export interface StaffLinkShiftView {
  shift_id: string
  station_id: string
  staff_id: string
  start_at: string
  end_at: string
  shift_status: ShiftStatus
  response_status: StaffResponseStatus
}

export interface CoverageWarningOut {
  station_id: string
  coverage_rule_id: string
  day_of_week: number
  window_start: string
  window_end: string
  minimum_staff: number
  scheduled_staff: number
}

// ---- Attendance (Epic 3) ----

export interface AttendanceEventOut {
  id: string
  shift_id: string
  status: AttendanceStatus
  source: AttendanceSource
  actor_user_id: string | null
  note: string | null
  recorded_at: string
}

export interface CurrentAttendanceOut {
  shift_id: string
  status: AttendanceStatus | null
}

// ---- Prep (Epic 4) ----

export interface PrepTemplateOut {
  id: string
  venue_id: string
  name: string
}

export interface PrepTemplateItemOut {
  id: string
  template_id: string
  station_id: string
  item: string
  quantity: string
  unit: string
  priority: number
  sort_order: number
}

export interface PrepTemplateDetailOut extends PrepTemplateOut {
  items: PrepTemplateItemOut[]
}

export interface PrepTaskOut {
  id: string
  venue_id: string
  service_day_id: string
  station_id: string
  item: string
  quantity: string
  unit: string
  priority: number
  status: PrepTaskStatus
  template_item_id: string | null
  carried_from_task_id: string | null
  carried_to_task_id: string | null
  carry_count: number
  added_after_close: boolean
}

export interface PrintablePrepTaskOut {
  station_id: string
  station_name: string
  item: string
  quantity: string
  unit: string
  priority: number
  status: PrepTaskStatus
}

// ---- Supplier orders (Epic 5) ----

export interface PurchaseOrderLineOut {
  id: string
  ingredient_id: string
  quantity: string
  unit: string
  delivery_note: string | null
  source: string
}

export interface DeliveryIssueOut {
  id: string
  issue_type: DeliveryIssueType
  evidence: string | null
  resolution: string | null
}

export interface PurchaseOrderOut {
  id: string
  venue_id: string
  supplier_id: string
  status: PurchaseOrderStatus
  required_delivery_date: string | null
  order_cycle: string | null
  idempotency_key: string | null
  sent_at: string | null
  sent_by: string | null
  provider_message_id: string | null
  recipient_snapshot: string | null
  last_error: string | null
  delivery_status: DeliveryStatus
  lines: PurchaseOrderLineOut[]
  delivery_issues: DeliveryIssueOut[]
}

// ---- Quick Capture (Epic 6) ----

export interface CaptureOut {
  id: string
  venue_id: string
  service_day_id: string
  raw_text: string
  capture_type: CaptureType
  matched_entity_type: MatchedEntityType | null
  matched_entity_id: string | null
  extracted_quantity: string | null
  extracted_unit: string | null
  confidence: string | null
  candidate_matches: Record<string, unknown>[] | null
  status: CaptureStatus
  decided_by: string | null
  decided_at: string | null
  added_after_close: boolean
}

export interface ConfirmCaptureResult {
  capture: CaptureOut
  result_type: string
  result_id: string
}

// ---- Handover (Epic 7) ----

export type HandoverItemType =
  | "prep_task"
  | "capture"
  | "equipment_issue"
  | "purchase_order"
  | "menu_availability_event"
  | "delivery_issue"

export interface HandoverItemOut {
  id: string
  handover_id: string
  included: boolean
  item_type: HandoverItemType
  item_id: string | null
}

export interface HandoverOut {
  id: string
  venue_id: string
  service_day_id: string
  note: string | null
  closed_by: string
  closed_at: string
  time_to_close_seconds: number
  items: HandoverItemOut[]
}

// ---- Chef Brief (Epic 8) ----

export interface RosteredStaffStatusOut {
  shift_id: string
  staff_id: string
  staff_name: string
  station_id: string
  start_at: string
  end_at: string
  attendance_status: string | null
}

export interface CoverageGapOut {
  station_id: string
  coverage_rule_id: string
  day_of_week: number
  window_start: string
  window_end: string
  minimum_staff: number
  scheduled_staff: number
}

export interface ApproachingCutoffOut {
  supplier_id: string
  supplier_name: string
  purchase_order_id: string
  cutoff_at: string
}

export interface EquipmentIssueOut {
  id: string
  equipment_item_id: string
  priority: EquipmentIssuePriority
  status: EquipmentIssueStatus
  photos: string | null
  resolution_notes: string | null
  opened_at: string
}

export interface MenuItemAvailabilityOut {
  menu_item_id: string
  menu_item_name: string
  status: MenuAvailabilityStatus
  quantity_remaining: string | null
  recorded_at: string
}

export interface ChefBriefOut {
  service_day_id: string
  business_date: string
  rostered_staff: RosteredStaffStatusOut[]
  coverage_gaps: CoverageGapOut[]
  priority_open_prep_tasks: PrepTaskOut[]
  approaching_order_cutoffs: ApproachingCutoffOut[]
  open_equipment_issues: EquipmentIssueOut[]
  yesterdays_handover: HandoverOut | null
  carried_forward_tasks: PrepTaskOut[]
  unavailable_or_low_menu_items: MenuItemAvailabilityOut[]
}

// ---- Kitchen Memory (Epic 9) ----

export interface RecipeOut {
  id: string
  venue_id: string
  name: string
}

export interface RecipeIngredientOut {
  ingredient_id: string
  ingredient_name: string
  quantity: string
  unit: string
}

export interface RecipeVersionOut {
  id: string
  recipe_id: string
  version_no: number
  yield_qty: string | null
  yield_unit: string | null
  prep_notes: string | null
  ingredients: RecipeIngredientOut[]
}

export interface RecipeDetailOut extends RecipeOut {
  current_version: RecipeVersionOut | null
  version_count: number
}

export interface MenuItemDetailOut extends MenuItemOut {
  recipes: RecipeDetailOut[]
}

export interface EquipmentItemIssueHistoryOut {
  equipment_item: EquipmentItemOut
  issues: EquipmentIssueOut[]
}

export type SearchResultType = "recipe" | "recipe_version" | "supplier_notes" | "equipment_issue" | "handover_note"

export interface SearchResultOut {
  result_type: SearchResultType
  entity_id: string
  title: string
  matched_text: string
}

// ---- Notifications (Epic 10) ----

export interface SentNotificationOut {
  action: string
  entity_type: string
  entity_id: string
  recipients: string[]
  subject: string
}

// ---- Pilot metrics (Epic 11) ----

export type PilotMetricAction =
  | "metrics.minutes_saved_reported"
  | "metrics.incident_logged"
  | "metrics.pilot_decision_recorded"

export interface PilotMetricEventOut {
  id: string
  action: PilotMetricAction
  entity_type: string
  entity_id: string
  after_data: Record<string, unknown> | null
  recorded_at: string
}
