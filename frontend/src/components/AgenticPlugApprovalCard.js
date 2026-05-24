import React from "react";
import "./AgenticPlugTaskView.css";

const RISK_LABELS = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const RISK_CLASSES = {
  low: "ap-risk-low",
  medium: "ap-risk-medium",
  high: "ap-risk-high",
  critical: "ap-risk-critical",
};

export const AgenticPlugApprovalCard = ({
  approvalRequest,
  onApprove,
  onDeny,
}) => {
  if (!approvalRequest) return null;

  const riskLabel = RISK_LABELS[approvalRequest.risk_level] || approvalRequest.risk_level;
  const riskClass = RISK_CLASSES[approvalRequest.risk_level] || "";

  return (
    <div className="ap-approval-card">
      <div className="ap-approval-header">
        <span className="ap-approval-icon">⚠</span>
        <h3>Approval Required</h3>
        <span className={`ap-risk-badge ${riskClass}`}>{riskLabel} Risk</span>
      </div>

      <div className="ap-approval-body">
        <div className="ap-approval-field">
          <span className="ap-field-label">Operation</span>
          <code className="ap-field-value">{approvalRequest.operation}</code>
        </div>

        <div className="ap-approval-field">
          <span className="ap-field-label">Target Connector</span>
          <code className="ap-field-value">
            {approvalRequest.target_connector}
          </code>
        </div>

        <div className="ap-approval-field">
          <span className="ap-field-label">Target Cluster</span>
          <code className="ap-field-value">
            {approvalRequest.target_cluster}
          </code>
        </div>

        <div className="ap-approval-field">
          <span className="ap-field-label">Command Summary</span>
          <pre className="ap-command-preview">
            {approvalRequest.command_summary}
          </pre>
        </div>

        {approvalRequest.template_summary && (
          <div className="ap-approval-field">
            <span className="ap-field-label">Template</span>
            <code className="ap-field-value">
              {approvalRequest.template_summary}
            </code>
          </div>
        )}

        {approvalRequest.affected_paths?.length > 0 && (
          <div className="ap-approval-field">
            <span className="ap-field-label">Affected Paths</span>
            <div className="ap-path-list">
              {approvalRequest.affected_paths.map((path, i) => (
                <code key={i} className="ap-path-item">
                  {path}
                </code>
              ))}
            </div>
          </div>
        )}

        <div className="ap-approval-field">
          <span className="ap-field-label">Risk Level</span>
          <span className={`ap-risk-badge ${riskClass}`}>{riskLabel}</span>
        </div>

        {approvalRequest.estimated_duration && (
          <div className="ap-approval-field">
            <span className="ap-field-label">Estimated Duration</span>
            <code className="ap-field-value">
              {approvalRequest.estimated_duration}
            </code>
          </div>
        )}

        {approvalRequest.requester_identity && (
          <div className="ap-approval-field">
            <span className="ap-field-label">Requester</span>
            <code className="ap-field-value">
              {approvalRequest.requester_identity}
            </code>
          </div>
        )}
      </div>

      <div className="ap-approval-actions">
        <button className="ap-approve-button" onClick={onApprove}>
          Approve
        </button>
        <button className="ap-deny-button" onClick={onDeny}>
          Deny
        </button>
      </div>
    </div>
  );
};
