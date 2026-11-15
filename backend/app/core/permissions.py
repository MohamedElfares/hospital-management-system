"""Roles, and later permissions, that decide what each user may do.

Roles and permissions live in code rather than in database tables, so they
are version-controlled, reviewed, and tested like any other code (plan §6,
ADR-0003). This module holds ``Role`` for now; ``Permission`` and the
role-to-permissions mapping arrive with ``require_permission`` in
Milestone 1.2 (IAM-4, issue #17). Routes must check permissions, never role
names.
"""

# Base class for enums whose members are also strings; a Role equals its stored value.
from enum import StrEnum


class Role(StrEnum):
    """The single role assigned to each user account.

    Every user has exactly one role (plan §3). Each member's value is the
    lowercase string stored in ``users.role``, listed in that column's CHECK
    constraint, and returned by the API, so changing a value needs a
    migration for both the stored rows and the constraint. All eight roles
    are defined from Phase 1, even though Patient arrives in Phase 4 and
    Customer Service and Manager in Phase 5, so the column and its CHECK
    constraint already accept them.

    Attributes:
        ADMIN: IT administrator. Manages every account, department, and
            branch, and reads the audit log. Never sees clinical data.
        RECEPTIONIST: Front desk. Registers patients, books appointments,
            and checks patients in; from Phase 4, also enables patients'
            portal access.
        NURSE: Nursing staff. Works the checked-in queue and records vitals.
        DOCTOR: Physician. Sees their own schedule, runs consultations,
            issues prescriptions, and reads their own patients' history.
        PHARMACIST: Branch pharmacist. Manages the medicine catalog, branch
            stock, and dispensing; from Phase 3, also stock transfers.
        PATIENT: Portal user linked to a patient record. Uses the
            ``/portal`` endpoints, scoped to their own record, plus sign-in
            and the shared directory. Every other endpoint rejects this role.
        CUSTOMER_SERVICE: Patient support. Handles tickets and reads patient
            contact details and appointments.
        MANAGER: Hospital management. Reads aggregate reports and manages
            staff accounts in every role except Admin and Manager. Never
            sees clinical data.
    """

    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
    NURSE = "nurse"
    DOCTOR = "doctor"
    PHARMACIST = "pharmacist"
    PATIENT = "patient"
    CUSTOMER_SERVICE = "customer_service"
    MANAGER = "manager"
