(() => {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  const button = document.getElementById("menuButton");

  const closeMenu = () => {
    sidebar?.classList.remove("open");
    backdrop?.classList.remove("visible");
  };

  button?.addEventListener("click", () => {
    sidebar?.classList.add("open");
    backdrop?.classList.add("visible");
  });
  backdrop?.addEventListener("click", closeMenu);

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm || "确定执行？")) event.preventDefault();
    });
  });

  document.querySelectorAll("[data-tabs]").forEach((tabs) => {
    const buttons = [...tabs.querySelectorAll("[data-tab]")];
    const panels = [...tabs.querySelectorAll("[data-tab-panel]")];
    const activate = (name) => {
      buttons.forEach((button) => {
        const active = button.dataset.tab === name;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", String(active));
      });
      panels.forEach((panel) => {
        const active = panel.dataset.tabPanel === name;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
    };
    buttons.forEach((button) => button.addEventListener("click", () => activate(button.dataset.tab)));
  });

  document.querySelectorAll("[data-modal-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.modalOpen);
      if (dialog?.showModal) dialog.showModal();
    });
  });
  document.querySelectorAll("[data-modal-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });

  document.querySelectorAll("[data-toggle-control]").forEach((control) => {
    const target = document.querySelector(`[data-toggle-target="${control.dataset.toggleControl}"]`);
    const sync = () => {
      const inactive = !control.checked;
      target?.classList.toggle("is-inactive", inactive);
      target?.querySelectorAll("input").forEach((input) => {
        input.readOnly = inactive;
        input.setAttribute("aria-disabled", String(inactive));
      });
    };
    control.addEventListener("change", sync);
    sync();
  });

  document.querySelectorAll("dialog.modal-dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  const taskLogDialog = document.getElementById("taskLogDialog");
  const taskLogTitle = document.getElementById("taskLogTitle");
  const taskLogStatus = document.getElementById("taskLogStatus");
  const taskLogSummary = document.getElementById("taskLogSummary");
  const taskLogMeta = document.getElementById("taskLogMeta");
  const taskLogOutput = document.getElementById("taskLogOutput");
  const statusLabels = {
    queued: "排队中", running: "执行中", success: "成功", partial: "部分完成",
    failed: "失败", blocked: "已阻止", timeout: "超时", unknown: "未运行",
  };
  let logTimer = null;
  let logUrl = "";
  let lastLogId = 0;

  const stopTaskLogPolling = () => {
    if (logTimer) window.clearInterval(logTimer);
    logTimer = null;
  };

  const setTaskLogStatus = (status, summary = "") => {
    const state = status || "unknown";
    taskLogStatus.className = `status ${state}`;
    taskLogStatus.textContent = statusLabels[state] || state;
    taskLogSummary.textContent = summary || "尚无执行记录";
  };

  const formatTaskLogLine = (event) => {
    const time = event.created_at ? event.created_at.replace("T", " ").slice(0, 19) : "--:--:--";
    const level = event.severity === "error" ? "ERROR" : event.severity === "warning" ? "WARN" : "INFO";
    return `[${time}] ${level}  ${event.message}`;
  };

  const fetchTaskLogs = async () => {
    if (!logUrl || !taskLogDialog?.open) return;
    try {
      const response = await fetch(`${logUrl}?after_id=${lastLogId}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`日志请求失败 (${response.status})`);
      const data = await response.json();
      const events = data.events || [];
      if (events.length) {
        taskLogOutput.textContent += `${events.map(formatTaskLogLine).join("\n")}\n`;
        lastLogId = events[events.length - 1].id;
        taskLogOutput.scrollTop = taskLogOutput.scrollHeight;
      } else if (!taskLogOutput.textContent) {
        taskLogOutput.textContent = "暂无日志，任务开始后会自动显示执行过程。\n";
      }
      const run = data.latest_run;
      setTaskLogStatus(run?.status || "unknown", run?.summary || "尚无执行记录");
      taskLogMeta.textContent = run?.started_at
        ? `执行记录 #${run.id} · ${run.started_at.replace("T", " ").slice(0, 19)} · 每 2 秒刷新`
        : "每 2 秒自动刷新";
    } catch (error) {
      setTaskLogStatus("unknown", error.message || "日志读取失败");
      taskLogMeta.textContent = "正在自动重试";
    }
  };

  const openTaskLog = (taskName, taskLogUrl) => {
    if (!taskLogDialog?.showModal || !taskLogUrl) return;
    stopTaskLogPolling();
    logUrl = taskLogUrl;
    lastLogId = 0;
    taskLogTitle.textContent = `${taskName || "任务"} · 执行日志`;
    taskLogOutput.textContent = "正在读取日志…\n";
    setTaskLogStatus("queued", "任务已进入队列，正在等待执行…");
    taskLogMeta.textContent = "每 2 秒自动刷新";
    taskLogDialog.showModal();
    fetchTaskLogs();
    logTimer = window.setInterval(fetchTaskLogs, 2000);
  };

  document.querySelectorAll("[data-task-log-open]").forEach((button) => {
    button.addEventListener("click", () => openTaskLog(button.dataset.taskName, button.dataset.taskLogUrl));
  });
  document.querySelectorAll("form[data-task-run]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submitButton = form.querySelector("button[type='submit']");
      if (submitButton?.disabled) return;
      if (submitButton) submitButton.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        if (!response.ok) throw new Error(`任务启动失败 (${response.status})`);
        await response.json();
        openTaskLog(form.dataset.taskName, form.dataset.taskLogUrl);
      } catch (error) {
        window.alert(error.message || "任务启动失败，请稍后重试。");
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  });
  taskLogDialog?.addEventListener("close", stopTaskLogPolling);

  if (window.lucide) window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
})();
