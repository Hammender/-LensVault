import type { WorkspacePermissionsPayload } from "../api/index";
import { workspacePermissionFields } from "../utils";

type PermissionEditorProps = {
  value: WorkspacePermissionsPayload;
  onChange: (value: WorkspacePermissionsPayload) => void;
  disabled?: boolean;
};

export default function PermissionEditor({ value, onChange, disabled = false }: PermissionEditorProps) {
  return (
    <div className="workspace-permissions">
      {workspacePermissionFields.map((item) => (
        <label key={item.key} className="workspace-permission">
          <input
            type="checkbox"
            checked={Boolean(value[item.key])}
            disabled={disabled}
            onChange={(event) => onChange({ ...value, [item.key]: event.target.checked })}
          />
          <span>{item.label}</span>
        </label>
      ))}
    </div>
  );
}
