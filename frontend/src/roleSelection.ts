/** A header always names one of the user's roles; an empty value means no roles. */
export function resolveActiveRole(assignedRoles: readonly string[], savedRole: string): string {
  return assignedRoles.includes(savedRole) ? savedRole : assignedRoles[0] ?? '';
}
