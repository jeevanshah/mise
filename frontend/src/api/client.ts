// Thin typed wrapper over the Mise API. One function per endpoint, grouped
// by the same module names the backend uses (app/api/routes/*.py) — see
// frontend/README.md for why this file has no cleverness in it: a direct,
// boring mirror of the backend surface is easier to keep in sync by hand
// than any generated-client machinery would be worth for one developer.

import type {
  AttendanceEventOut,
  AttendanceStatus,
  CaptureOut,
  ChefBriefOut,
  ConfirmCaptureResult,
  CoverageRuleOut,
  CoverageWarningOut,
  CurrentAttendanceOut,
  DeliveryIssueOut,
  DeliveryIssueType,
  EquipmentItemIssueHistoryOut,
  EquipmentItemOut,
  EquipmentIssuePriority,
  HandoverOut,
  IngredientOut,
  InviteUserResponse,
  MagicLinkRequestResponse,
  MatchedEntityType,
  MeResponse,
  MembershipRole,
  MenuAvailabilityStatus,
  MenuItemDetailOut,
  MenuItemOut,
  OrganisationCreateResponse,
  PilotMetricEventOut,
  PrepTaskOut,
  PrepTaskStatus,
  PrepTemplateDetailOut,
  PrepTemplateItemOut,
  PrepTemplateOut,
  PrintablePrepTaskOut,
  PublishResultOut,
  PurchaseOrderOut,
  RecipeDetailOut,
  RecipeOut,
  RecipeVersionOut,
  SearchResultOut,
  SentNotificationOut,
  ServiceDayOut,
  ShiftOut,
  StaffDetailOut,
  StaffLinkShiftView,
  StaffOut,
  StaffResponseStatus,
  StationOut,
  SupplierOut,
  TokenResponse,
  VenueOut,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

let authToken: string | null = null

/** Called once at app startup (and after login/logout) — kept as a module
 * variable rather than re-reading localStorage on every request. */
export function setAuthToken(token: string | null): void {
  authToken = token
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Record<string, string | undefined> } = {},
): Promise<T> {
  const { method = 'GET', body, query } = options
  const url = new URL(API_BASE + path)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, value)
    }
  }

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`

  const response = await fetch(url.toString(), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 204) return undefined as T

  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()

  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? (payload as { detail: unknown }).detail
      : payload
    throw new ApiError(response.status, detail)
  }

  return payload as T
}

/** For the two PDF-download endpoints — returns a Blob URL the caller can
 * point a link/iframe at, rather than trying to force this through the
 * JSON path above. */
async function requestBlob(path: string, query?: Record<string, string | undefined>): Promise<Blob> {
  const url = new URL(API_BASE + path)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, value)
    }
  }
  const headers: Record<string, string> = {}
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  const response = await fetch(url.toString(), { headers })
  if (!response.ok) throw new ApiError(response.status, await response.text())
  return response.blob()
}

export const api = {
  auth: {
    requestLink: (email: string) => request<MagicLinkRequestResponse>('/auth/request-link', { method: 'POST', body: { email } }),
    verify: (token: string) => request<TokenResponse>('/auth/verify', { method: 'POST', body: { token } }),
    me: () => request<MeResponse>('/auth/me'),
  },

  onboarding: {
    createOrganisation: (body: { organisation_name: string; venue_name: string; timezone?: string; business_day_boundary?: string }) =>
      request<OrganisationCreateResponse>('/organisations', { method: 'POST', body }),
    getVenue: (venueId: string) => request<VenueOut>(`/venues/${venueId}`),
    updateVenue: (venueId: string, body: { timezone?: string; business_day_boundary?: string }) =>
      request<VenueOut>(`/venues/${venueId}`, { method: 'PATCH', body }),
    invite: (venueId: string, body: { email: string; role: MembershipRole }) =>
      request<InviteUserResponse>(`/venues/${venueId}/invite`, { method: 'POST', body }),
  },

  staffing: {
    listStations: (venueId: string) => request<StationOut[]>(`/venues/${venueId}/stations`),
    createStation: (venueId: string, body: { name: string }) =>
      request<StationOut>(`/venues/${venueId}/stations`, { method: 'POST', body }),
    listStaff: (venueId: string) => request<StaffOut[]>(`/venues/${venueId}/staff`),
    getStaff: (venueId: string, staffId: string) => request<StaffDetailOut>(`/venues/${venueId}/staff/${staffId}`),
    createStaff: (venueId: string, body: { name: string; user_id?: string; contact_email?: string }) =>
      request<StaffOut>(`/venues/${venueId}/staff`, { method: 'POST', body }),
    addStaffSkill: (venueId: string, staffId: string, body: { station_id: string; trained?: boolean }) =>
      request(`/venues/${venueId}/staff/${staffId}/skills`, { method: 'POST', body }),
    listCoverageRules: (venueId: string, stationId: string) =>
      request<CoverageRuleOut[]>(`/venues/${venueId}/stations/${stationId}/coverage-rules`),
    createCoverageRule: (
      venueId: string,
      stationId: string,
      body: { day_of_week: number; window_start: string; window_end: string; minimum_staff?: number },
    ) => request<CoverageRuleOut>(`/venues/${venueId}/stations/${stationId}/coverage-rules`, { method: 'POST', body }),
  },

  catalog: {
    listSuppliers: (venueId: string) => request<SupplierOut[]>(`/venues/${venueId}/suppliers`),
    createSupplier: (venueId: string, body: { name: string; contact_email?: string; order_days?: string; cutoff_time?: string; notes?: string }) =>
      request<SupplierOut>(`/venues/${venueId}/suppliers`, { method: 'POST', body }),
    updateSupplierNotes: (venueId: string, supplierId: string, notes: string | null) =>
      request<SupplierOut>(`/venues/${venueId}/suppliers/${supplierId}/notes`, { method: 'PATCH', body: { notes } }),
    listIngredients: (venueId: string) => request<IngredientOut[]>(`/venues/${venueId}/ingredients`),
    createIngredient: (venueId: string, body: { name: string; unit: string; ordering_unit: string; preferred_supplier_id?: string }) =>
      request<IngredientOut>(`/venues/${venueId}/ingredients`, { method: 'POST', body }),
    listMenuItems: (venueId: string) => request<MenuItemOut[]>(`/venues/${venueId}/menu-items`),
    createMenuItem: (venueId: string, name: string) =>
      request<MenuItemOut>(`/venues/${venueId}/menu-items`, { method: 'POST', body: { name } }),
    listEquipmentItems: (venueId: string) => request<EquipmentItemOut[]>(`/venues/${venueId}/equipment-items`),
    createEquipmentItem: (venueId: string, body: { name: string; location?: string; repair_contact?: string }) =>
      request<EquipmentItemOut>(`/venues/${venueId}/equipment-items`, { method: 'POST', body }),
  },

  serviceDays: {
    current: (venueId: string) => request<ServiceDayOut>(`/venues/${venueId}/service-days/current`),
    start: (venueId: string, businessDate?: string) =>
      request<ServiceDayOut>(`/venues/${venueId}/service-days/start`, { method: 'POST', body: { business_date: businessDate } }),
  },

  roster: {
    listShifts: (venueId: string, params: { week_start?: string; business_date?: string }) =>
      request<ShiftOut[]>(`/venues/${venueId}/shifts`, { query: params }),
    getShift: (venueId: string, shiftId: string) => request<ShiftOut>(`/venues/${venueId}/shifts/${shiftId}`),
    createShift: (venueId: string, body: { station_id: string; staff_id: string; start_at: string; end_at: string }) =>
      request<ShiftOut>(`/venues/${venueId}/shifts`, { method: 'POST', body }),
    cancelShift: (venueId: string, shiftId: string) => request<ShiftOut>(`/venues/${venueId}/shifts/${shiftId}/cancel`, { method: 'POST' }),
    publishShift: (venueId: string, shiftId: string) =>
      request<PublishResultOut>(`/venues/${venueId}/shifts/${shiftId}/publish`, { method: 'POST' }),
    respondToShift: (venueId: string, shiftId: string, response: StaffResponseStatus) =>
      request<ShiftOut>(`/venues/${venueId}/shifts/${shiftId}/respond`, { method: 'POST', body: { response } }),
    publishWeek: (venueId: string, weekStart: string) =>
      request<PublishResultOut[]>(`/venues/${venueId}/rosters/publish-week`, { method: 'POST', body: { week_start: weekStart } }),
    copyWeek: (venueId: string, sourceWeekStart: string, targetWeekStart: string) =>
      request<ShiftOut[]>(`/venues/${venueId}/rosters/copy-week`, {
        method: 'POST',
        body: { source_week_start: sourceWeekStart, target_week_start: targetWeekStart },
      }),
    coverageWarnings: (venueId: string, businessDate: string) =>
      request<CoverageWarningOut[]>(`/venues/${venueId}/service-days/${businessDate}/coverage-warnings`),
    rosterPdfUrl: (venueId: string, weekStart: string) => `${API_BASE}/venues/${venueId}/rosters/pdf?week_start=${weekStart}`,
    downloadRosterPdf: (venueId: string, weekStart: string) => requestBlob(`/venues/${venueId}/rosters/pdf`, { week_start: weekStart }),
    viewStaffLink: (token: string) => request<StaffLinkShiftView>(`/staff-links/${token}`),
    respondViaLink: (token: string, response: StaffResponseStatus) =>
      request<StaffLinkShiftView>(`/staff-links/${token}/respond`, { method: 'POST', body: { response } }),
  },

  attendance: {
    logEvent: (venueId: string, shiftId: string, body: { status: AttendanceStatus; note?: string }) =>
      request<AttendanceEventOut>(`/venues/${venueId}/shifts/${shiftId}/attendance-events`, { method: 'POST', body }),
    listEvents: (venueId: string, shiftId: string) =>
      request<AttendanceEventOut[]>(`/venues/${venueId}/shifts/${shiftId}/attendance-events`),
    current: (venueId: string, shiftId: string) =>
      request<CurrentAttendanceOut>(`/venues/${venueId}/shifts/${shiftId}/attendance`),
    checkInViaLink: (token: string, status: AttendanceStatus) =>
      request<AttendanceEventOut>(`/staff-links/${token}/attendance-events`, { method: 'POST', body: { status } }),
  },

  prep: {
    listTemplates: (venueId: string) => request<PrepTemplateOut[]>(`/venues/${venueId}/prep-templates`),
    getTemplate: (venueId: string, templateId: string) =>
      request<PrepTemplateDetailOut>(`/venues/${venueId}/prep-templates/${templateId}`),
    createTemplate: (venueId: string, name: string) =>
      request<PrepTemplateOut>(`/venues/${venueId}/prep-templates`, { method: 'POST', body: { name } }),
    addTemplateItem: (
      venueId: string,
      templateId: string,
      body: { station_id: string; item: string; quantity: string; unit: string; priority?: number },
    ) => request<PrepTemplateItemOut>(`/venues/${venueId}/prep-templates/${templateId}/items`, { method: 'POST', body }),
    applyTemplate: (venueId: string, businessDate: string, templateId: string, addedAfterClose = false) =>
      request<PrepTaskOut[]>(`/venues/${venueId}/service-days/${businessDate}/prep-tasks/apply-template`, {
        method: 'POST',
        body: { template_id: templateId, added_after_close: addedAfterClose },
      }),
    listTasks: (venueId: string, businessDate: string) =>
      request<PrepTaskOut[]>(`/venues/${venueId}/service-days/${businessDate}/prep-tasks`),
    printableList: (venueId: string, businessDate: string) =>
      request<PrintablePrepTaskOut[]>(`/venues/${venueId}/service-days/${businessDate}/prep-tasks/printable`),
    updateTaskStatus: (venueId: string, taskId: string, status: PrepTaskStatus) =>
      request<PrepTaskOut>(`/venues/${venueId}/prep-tasks/${taskId}/status`, { method: 'PATCH', body: { status } }),
    carryForward: (venueId: string, businessDate: string, toBusinessDate: string) =>
      request<PrepTaskOut[]>(`/venues/${venueId}/service-days/${businessDate}/prep-tasks/carry-forward`, {
        method: 'POST',
        body: { to_business_date: toBusinessDate },
      }),
  },

  purchaseOrders: {
    list: (venueId: string) => request<PurchaseOrderOut[]>(`/venues/${venueId}/purchase-orders`),
    get: (venueId: string, poId: string) => request<PurchaseOrderOut>(`/venues/${venueId}/purchase-orders/${poId}`),
    addOrMergeLine: (
      venueId: string,
      body: {
        supplier_id: string
        ingredient_id: string
        quantity: string
        unit?: string
        required_delivery_date?: string
        order_cycle?: string
      },
    ) => request<PurchaseOrderOut>(`/venues/${venueId}/purchase-orders/lines`, { method: 'POST', body }),
    updateLineQuantity: (venueId: string, poId: string, lineId: string, quantity: string) =>
      request<PurchaseOrderOut>(`/venues/${venueId}/purchase-orders/${poId}/lines/${lineId}`, { method: 'PATCH', body: { quantity } }),
    send: (venueId: string, poId: string) => request<PurchaseOrderOut>(`/venues/${venueId}/purchase-orders/${poId}/send`, { method: 'POST' }),
    markDelivery: (venueId: string, poId: string, body: { partial: boolean; line_notes?: Record<string, string> }) =>
      request<PurchaseOrderOut>(`/venues/${venueId}/purchase-orders/${poId}/delivery`, { method: 'POST', body }),
    logDeliveryIssue: (venueId: string, poId: string, body: { issue_type: DeliveryIssueType; evidence?: string; resolution?: string }) =>
      request<DeliveryIssueOut>(`/venues/${venueId}/purchase-orders/${poId}/delivery-issues`, { method: 'POST', body }),
  },

  capture: {
    create: (venueId: string, body: { raw_text: string; business_date?: string; added_after_close?: boolean }) =>
      request<CaptureOut>(`/venues/${venueId}/captures`, { method: 'POST', body }),
    list: (venueId: string) => request<CaptureOut[]>(`/venues/${venueId}/captures`),
    get: (venueId: string, captureId: string) => request<CaptureOut>(`/venues/${venueId}/captures/${captureId}`),
    confirm: (
      venueId: string,
      captureId: string,
      body: {
        entity_type?: MatchedEntityType
        entity_id?: string
        quantity?: string
        unit?: string
        supplier_id?: string
        required_delivery_date?: string
        order_cycle?: string
        availability_status?: MenuAvailabilityStatus
        quantity_remaining?: string
        priority?: EquipmentIssuePriority
        photos?: string
      },
    ) => request<ConfirmCaptureResult>(`/venues/${venueId}/captures/${captureId}/confirm`, { method: 'POST', body }),
    reject: (venueId: string, captureId: string, reason?: string) =>
      request<CaptureOut>(`/venues/${venueId}/captures/${captureId}/reject`, { method: 'POST', body: { reason } }),
  },

  handover: {
    close: (venueId: string, businessDate: string, note?: string) =>
      request<HandoverOut>(`/venues/${venueId}/service-days/${businessDate}/close`, { method: 'POST', body: { note } }),
    reopen: (venueId: string, businessDate: string, reason: string) =>
      request(`/venues/${venueId}/service-days/${businessDate}/reopen`, { method: 'POST', body: { reason } }),
    get: (venueId: string, businessDate: string) => request<HandoverOut>(`/venues/${venueId}/service-days/${businessDate}/handover`),
    setItemIncluded: (venueId: string, itemId: string, included: boolean) =>
      request<HandoverOut>(`/venues/${venueId}/handover-items/${itemId}/included`, { method: 'PATCH', body: { included } }),
    downloadPdf: (venueId: string, businessDate: string) =>
      requestBlob(`/venues/${venueId}/service-days/${businessDate}/handover/pdf`),
  },

  chefBrief: {
    get: (venueId: string, businessDate?: string) => request<ChefBriefOut>(`/venues/${venueId}/chef-brief`, { query: { business_date: businessDate } }),
  },

  kitchenMemory: {
    listRecipes: (venueId: string) => request<RecipeOut[]>(`/venues/${venueId}/recipes`),
    getRecipe: (venueId: string, recipeId: string) => request<RecipeDetailOut>(`/venues/${venueId}/recipes/${recipeId}`),
    listVersions: (venueId: string, recipeId: string) => request<RecipeVersionOut[]>(`/venues/${venueId}/recipes/${recipeId}/versions`),
    createRecipe: (venueId: string, name: string) => request<RecipeOut>(`/venues/${venueId}/recipes`, { method: 'POST', body: { name } }),
    createVersion: (
      venueId: string,
      recipeId: string,
      body: { yield_qty?: string; yield_unit?: string; prep_notes?: string; ingredients: { ingredient_id: string; quantity: string; unit: string }[] },
    ) => request<RecipeVersionOut>(`/venues/${venueId}/recipes/${recipeId}/versions`, { method: 'POST', body }),
    linkRecipeToMenuItem: (venueId: string, menuItemId: string, recipeId: string) =>
      request(`/venues/${venueId}/menu-items/${menuItemId}/recipes`, { method: 'POST', body: { recipe_id: recipeId } }),
    getMenuItem: (venueId: string, menuItemId: string) => request<MenuItemDetailOut>(`/venues/${venueId}/menu-items/${menuItemId}`),
    equipmentIssueHistory: (venueId: string, equipmentItemId: string) =>
      request<EquipmentItemIssueHistoryOut>(`/venues/${venueId}/equipment-items/${equipmentItemId}/issues`),
    search: (venueId: string, q: string) => request<SearchResultOut[]>(`/venues/${venueId}/kitchen-memory/search`, { query: { q } }),
  },

  notifications: {
    runChecks: (venueId: string) => request<SentNotificationOut[]>(`/venues/${venueId}/notifications/run-checks`, { method: 'POST' }),
  },

  pilotMetrics: {
    recordMinutesSaved: (venueId: string, weekStart: string, minutesSaved: number) =>
      request<PilotMetricEventOut>(`/venues/${venueId}/metrics/minutes-saved`, {
        method: 'POST',
        body: { week_start: weekStart, minutes_saved: minutesSaved },
      }),
    logIncident: (venueId: string, body: { business_date: string; incident_type: 'missed_order' | 'handover_failure'; description: string }) =>
      request<PilotMetricEventOut>(`/venues/${venueId}/metrics/incidents`, { method: 'POST', body }),
    recordDecision: (venueId: string, willPayAtProposedPrice: boolean, notes?: string) =>
      request<PilotMetricEventOut>(`/venues/${venueId}/metrics/pilot-decision`, {
        method: 'POST',
        body: { will_pay_at_proposed_price: willPayAtProposedPrice, notes },
      }),
    list: (venueId: string) => request<PilotMetricEventOut[]>(`/venues/${venueId}/metrics`),
  },
}

export { API_BASE }
