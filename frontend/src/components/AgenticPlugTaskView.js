import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import "./AgenticPlugTaskView.css";
import { AgenticPlugTaskCard } from "./AgenticPlugTaskCard";
import { AgenticPlugApprovalCard } from "./AgenticPlugApprovalCard";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

const TASK_STATES = {
  task_created: "Created",
  task_running: "Running",
  approval_required: "Approval Required",
  approval_denied: "Denied",
  approval_granted: "Approved",
  job_submitted: "Submitted",
  job_queued: "Queued",
  job_running: "Job Running",
  job_completed: "Completed",
  job_failed: "Failed",
  artifact_available: "Artifact Ready",
  github_handoff: "Handoff Ready",
};

export const AgenticPlugTaskView = () => {
  const [tasks, setTasks] = useState([]);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [logs, setLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [scenario, setScenario] = useState("default");

  const fetchTasks = useCallback(async () => {
    try {
      const res = await axios.get(`${BACKEND_URL}/agenticplug/tasks`);
      setTasks(res.data.tasks || []);
    } catch (err) {
      console.error("Error fetching tasks:", err);
    }
  }, []);

  const fetchTaskDetail = useCallback(async (taskId) => {
    try {
      const res = await axios.get(`${BACKEND_URL}/agenticplug/tasks/${taskId}`);
      setSelectedTask(res.data);
    } catch (err) {
      console.error("Error fetching task detail:", err);
    }
  }, []);

  const fetchLogs = useCallback(async (taskId) => {
    try {
      const res = await axios.get(`${BACKEND_URL}/agenticplug/tasks/${taskId}/logs`);
      setLogs(res.data.logs || []);
    } catch (err) {
      console.error("Error fetching task logs:", err);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(() => {
      fetchTasks();
      if (selectedTaskId) {
        fetchTaskDetail(selectedTaskId);
        fetchLogs(selectedTaskId);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [fetchTasks, selectedTaskId, fetchTaskDetail, fetchLogs]);

  const handleSelectTask = (taskId) => {
    setSelectedTaskId(taskId);
    fetchTaskDetail(taskId);
    fetchLogs(taskId);
  };

  const handleGenerateMock = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await axios.post(
        `${BACKEND_URL}/agenticplug/tasks/mock/generate?scenario=${scenario}&title=Mock+${scenario}+task`
      );
      const newTask = res.data;
      setSelectedTaskId(newTask.task_id);
      await fetchTasks();
      await fetchTaskDetail(newTask.task_id);
    } catch (err) {
      console.error("Error generating mock task:", err);
      setError("Failed to generate mock task. Is the backend running?");
    } finally {
      setIsLoading(false);
    }
  };

  const handleApprove = async (taskId) => {
    try {
      await axios.post(`${BACKEND_URL}/agenticplug/tasks/${taskId}/approve`);
      fetchTaskDetail(taskId);
      fetchTasks();
    } catch (err) {
      console.error("Error approving task:", err);
    }
  };

  const handleDeny = async (taskId) => {
    try {
      await axios.post(`${BACKEND_URL}/agenticplug/tasks/${taskId}/deny`);
      fetchTaskDetail(taskId);
      fetchTasks();
    } catch (err) {
      console.error("Error denying task:", err);
    }
  };

  const selectedTaskObj = tasks.find((t) => t.task_id === selectedTaskId);

  return (
    <div className="agenticplug-task-view">
      <div className="agenticplug-header">
        <h2>AgenticPlug Tasks</h2>
        <div className="mock-controls">
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
            className="scenario-select"
          >
            <option value="default">Default (success)</option>
            <option value="approval_required">Approval Required</option>
            <option value="simulated_failure">Simulated Failure</option>
          </select>
          <button
            onClick={handleGenerateMock}
            disabled={isLoading}
            className="generate-button"
          >
            {isLoading ? "Generating..." : "Generate Mock Task"}
          </button>
        </div>
      </div>

      {error && <p className="ap-error">{error}</p>}

      <div className="agenticplug-content">
        <div className="ap-task-list">
          <h3>Tasks</h3>
          {tasks.length === 0 ? (
            <p className="ap-empty">
              No tasks yet. Generate a mock task to get started.
            </p>
          ) : (
            tasks.map((task) => (
              <AgenticPlugTaskCard
                key={task.task_id}
                task={task}
                isSelected={task.task_id === selectedTaskId}
                onSelect={() => handleSelectTask(task.task_id)}
                stateLabel={TASK_STATES[task.state] || task.state}
              />
            ))
          )}
        </div>

        <div className="ap-task-detail">
          {selectedTaskObj ? (
            <>
              {selectedTaskObj.state === "approval_required" &&
                selectedTaskObj.approval_request && (
                  <AgenticPlugApprovalCard
                    approvalRequest={selectedTaskObj.approval_request}
                    onApprove={() => handleApprove(selectedTaskObj.task_id)}
                    onDeny={() => handleDeny(selectedTaskObj.task_id)}
                  />
                )}

              <div className="ap-event-log">
                <h3>Events</h3>
                <div className="ap-log-container">
                  {(selectedTask || selectedTaskObj).events?.length > 0 ? (
                    (selectedTask || selectedTaskObj).events.map(
                      (event, index) => (
                        <div
                          key={index}
                          className={`ap-event ap-event-${event.state}`}
                        >
                          <span className="ap-event-time">
                            {event.timestamp
                              ? new Date(event.timestamp).toLocaleTimeString()
                              : ""}
                          </span>
                          <span className="ap-event-state">
                            {TASK_STATES[event.state] || event.state}
                          </span>
                          <span className="ap-event-message">
                            {event.message}
                          </span>
                        </div>
                      )
                    )
                  ) : (
                    <p className="ap-empty">No events recorded.</p>
                  )}
                </div>
              </div>

              <div className="ap-logs">
                <h3>Logs (bounded)</h3>
                <div className="ap-log-container ap-log-output">
                  {logs.length > 0 ? (
                    logs.map((line, index) => (
                      <div key={index} className="ap-log-line">
                        {line}
                      </div>
                    ))
                  ) : (
                    <p className="ap-empty">No logs available.</p>
                  )}
                </div>
              </div>

              {(selectedTaskObj.state === "artifact_available" ||
                selectedTaskObj.state === "github_handoff") && (
                <div className="ap-artifacts">
                  <h3>Artifacts & Links</h3>
                  {selectedTaskObj.artifact_url && (
                    <div className="ap-artifact-link">
                      <span className="ap-link-icon">📦</span>
                      <span>Artifact: </span>
                      <code>{selectedTaskObj.artifact_url}</code>
                    </div>
                  )}
                  {selectedTaskObj.github_handoff_url && (
                    <div className="ap-artifact-link">
                      <span className="ap-link-icon">🐙</span>
                      <span>GitHub Handoff: </span>
                      <code>{selectedTaskObj.github_handoff_url}</code>
                    </div>
                  )}
                </div>
              )}

              {selectedTaskObj.exit_code != null && (
                <div
                  className={`ap-exit-code ${
                    selectedTaskObj.exit_code === 0
                      ? "ap-exit-success"
                      : "ap-exit-failure"
                  }`}
                >
                  Exit code: {selectedTaskObj.exit_code}
                </div>
              )}
            </>
          ) : (
            <div className="ap-no-selection">
              <p>Select a task from the list or generate a new mock task.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
