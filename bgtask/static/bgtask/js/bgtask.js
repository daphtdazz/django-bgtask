window.BG_TASK_ADDED = true;

const STATE_TO_EMOJI = {
    "not_started": "⏱️",
    "running": "🏃🏽‍♀️",
    "success": "✅",
    "partial_success": "⚠️",
    "failed": "❌",
};

const OUT_OF_DATE_PERIOD_S = 20;
const REFRESH_PERIOD_MS = 5000;
const TIME_TO_REDUCED_REFRESH_PERIOD_S = 300;
const REDUCED_REFRESH_PERIOD_S = 60;
const PROGRESS_REFRESH_MS = 100;

function millisecondsToTimeAgoString(ms) {
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) {
    if (days === 1) {
      return `${days} day, ${hours % 24} hours ago`;
    }
    return `${days} days ago`;
  }
  if (hours > 0) {
    if (hours === 1) {
      return `${hours} hour, ${minutes % 60} minutes ago`;
    }
    return `${hours} hours ago`;
  }
  if (minutes > 0) {
    if (minutes === 1) {
      return `${minutes} minute, ${seconds % 60} seconds ago`;
    }
    return `${minutes} minutes ago`;
  }
  return `${seconds} seconds ago`;
}

// -------------------------------------------------------------------------------------------------
// Generic live-looking progress bar manager.
// -------------------------------------------------------------------------------------------------
class ProgressState {
    constructor(element, {value, max} = {value: null, max: null}) {
        this.element = element;

        this.animationFrameRequestId = null;

        this.max = max;
        // set it immediately initially
        this.progEle.value = value;
    }

    update({ max, value, isOutOfDate }) {
      this.max = max;
      this.value = value;
      if (isOutOfDate) {
        this.element.getElementsByClassName("bgtask-out-of-date")[0].style.display = null;
      } else {
        this.element.getElementsByClassName("bgtask-out-of-date")[0].style.display = "none";
      }
    }

    get progEle() {
      return this.element.getElementsByTagName("progress")[0];
    }

    get max() {
      return this.progEle.max;
    }
    set max(max) {
      this.progEle.max = max;
    }
    get value() {
      return this.progEle.value;
    }
    set value(value) {
      // we're going to start the timer again if it was already running.
      this._cancelTimer();
      const currentValue = this.progEle.value || 0;
      if (value === null || value === undefined) {
          // console.info("null value");
          this.progEle.removeAttribute("value");
          return
      }
      if (value >= this.max) {
          // console.info("greater than max", value, this.max);
          this.progEle.value = this.max;
          return;
      }
      if (currentValue === value) {
          // console.info("already at value", currentValue, value);
          return;
      }

      // completion due in the refresh period plus a bit so that we don't get there too soon
      // and cause a visible stop: we would rather the next update arrived before we reached the
      // target value
      const now = new Date();
      const completionDue = new Date(now.getTime() + REFRESH_PERIOD_MS + PROGRESS_REFRESH_MS);
      const initialMSToCompletion = completionDue - now;
      const completionDueHighRes = performance.now() + initialMSToCompletion;
      const previousValue = currentValue;

      let startTimestamp = null;

      const updateProgressStep = (now) => {
        if (startTimestamp === null) {
          startTimestamp = now;
          this.animationFrameRequestId = window.requestAnimationFrame(updateProgressStep);
          return;
        }
        const msRemaining = completionDueHighRes - now;
        const newValue = previousValue + (
            ((initialMSToCompletion - msRemaining) / initialMSToCompletion)
            * (value - previousValue)
        );

        if (completionDue <= now || Math.abs((value - newValue) / this.progEle.max) < 0.001) {
          this.progEle.value = value;
          return;
        }

        this.progEle.value = newValue;
        this.animationFrameRequestId = window.requestAnimationFrame(updateProgressStep);
      }

      this.animationFrameRequestId = window.requestAnimationFrame(updateProgressStep);
    }

    _cancelTimer() {
        if (this.animationFrameRequestId !== null) {
          window.cancelAnimationFrame(this.animationFrameRequestId)
        }
        this.animationFrameRequestId = null;
    }
}

// -------------------------------------------------------------------------------------------------
// Manage the progress div (what's in the column the admin list view of a taskable model).
// -------------------------------------------------------------------------------------------------
class TaskProgressDiv {
  constructor (divOrId, task) {
    this.taskId = task.id;
    let div = divOrId;
    if (typeof divOrId === 'string') {
      div = document.getElementById(divOrId);
    }
    this.div = div;
    this.stateEle = this.div.getElementsByClassName("bgtask-state")[0];

    this.pgstate = new ProgressState(
      // need to initialize values here and not rely on updateFromTask to get instant progress
      // bar values
      this.div, {value: task.steps_completed, max: task.steps_to_complete}
    );

    this.updateFromTask(task);
  }

  attachToPoller(poller) {
    poller.monitorTask(this.taskId, task => this.updateFromTask(task));
  }

  updateFromTask(task) {
    this.div.title = "";

    switch (task.state) {
      case "partial_success":
        this._hideProgress();
        this._showState();
        this._addTitle("Some errors occurred");
        break;
      case "failed":
        this._hideProgress();
        this._showState();
        let title = "Task failed";
        for (const error of task.errors) {
          if (error.traceback) {
            title = `${title}\n${error.traceback}\n\n${error.error_message}`;
            break;
          }
        }
        this._addTitle(title);
        break;
      case "success":
        this._hideProgress();
        this._showState();
        this._addTitle("Task succeeded");
        break;
      case "not_started":
        this._hideProgress();
        this._showState();
        this._addTitle("")
        break;
      case "running":
        this._showProgress();
        this._hideState();
        break;
    }

    const isOutOfDate = (
      !["success", "partial_success", "not_started", "failed"].includes(task.state)
      && (new Date() - task.updated) > OUT_OF_DATE_PERIOD_S * 1000
    );

    if (isOutOfDate ) {
      this._addTitle("This task has not been updated for a while");
    }

    this.stateEle.innerHTML = `${STATE_TO_EMOJI[task.state] || "❓"}`;

    this.pgstate.update({ max: task.steps_to_complete, value: task.steps_completed, isOutOfDate });
  }

  _addTitle(title) {
    if (!this.div.title) {
      this.div.title = title;
      return;
    }
    this.div.title = this.div.title + " | " + title;
  }
  _hideProgress() {
    this.pgstate.progEle.style.display = "none";
  }
  _showProgress() {
    this.pgstate.progEle.style.display = null;
  }
  _hideState() {
    this.stateEle.style.display = "none";
  }
  _showState() {
    this.stateEle.style.display = null;
  }
}

// -------------------------------------------------------------------------------------------------
// Manage an element which just shows one field from the task
// -------------------------------------------------------------------------------------------------
class TaskFieldElement {
  constructor (element, fieldName, task) {
    this.taskId = task.id;
    this.element = element;
    this.fieldName = fieldName;
    this.updateFromTask(task);
  }

  attachToPoller(poller) {
    poller.monitorTask(this.taskId, task => this.updateFromTask(task));
  }

  updateFromTask(task) {
    this.element.innerHTML = task[this.fieldName];
  }
}

// -------------------------------------------------------------------------------------------------
// Manage a task detail div
// -------------------------------------------------------------------------------------------------
class BGTaskDetailViewDiv {
  constructor (div, task, poller) {
    this.taskId = task.id;
    this.div = div;
    this.progressDiv = new TaskProgressDiv(
      div.getElementsByClassName("bgtask-status-div")[0], task, poller
    );
    this.errorRows = [];

    div.setAttribute('id', task.id);

    this.updateFromTask(task);
  }

  static fixTraceback(tb) {
    // Just removes all but the last three path components of each file referenced in the traceback.
    // E.g. /User/bart/src/repo/module/submodule/blah.py -> .../module/submodule/blah.py
    const tbLines = tb.split('\n');
    const paths = [];
    const newLines = [];
    for (const line of tbLines) {
      const filePathRegex = /( *)File ".*((\/[^\/]+){3})"(.*)/.exec(line);
      if (filePathRegex === null) {
        newLines.push(line);
        continue;
      }
      newLines.push(`${filePathRegex[1]}File "...${filePathRegex[2]}"${filePathRegex[4]}`);
    }
    // the first two characters are always spaces
    return newLines.map(nl => nl.slice(2)).join('\n');
  }

  attachToPoller(poller) {
    poller.monitorTask(this.taskId, task => this.updateFromTask(task));
  }

  updateFromTask(task) {
    // console.log(`BGTaskDetailViewDiv.updateFromTask`, task);
    setText(this.div, "bgtask-name", `${task.name}`);
    setText(this.div, "bgtask-text-status", `State: ${task.state}, started at ${task.started_at}`);

    switch (task.state) {
      case "partial_success":
      case "failure":
        this._showErrors();
        break;
    }
    this._updateErrorRowsFromTask(task);
    this.progressDiv.updateFromTask(task);
  }

  _showErrors() {
    this.div.getElementsByClassName("bgtask-errors-div")[0].style.display = null;
  }

  _updateErrorRowsFromTask(task) {
    // Just add new errors, assuming that the order of the errors stays consistent and errors are
    // only added to the end.
    const errorsTable = this.div.getElementsByClassName("bgtask-errors-table")[0];
    for (const newError of task.errors.slice(this.errorRows.length)) {
      const newRow = cloneTemplateInto("bgtask-error-row", errorsTable);
      const errorDateTime = new Date(newError.datetime);

      this.errorRows.push(newRow);
      setText(newRow, 'bgtask-error-row-group', newError.steps_identifier);
      setText(newRow, 'bgtask-error-row-num', newError.num_failed_steps);
      setText(newRow, 'bgtask-error-row-error', newError.error_message);
      // only want the HH:MM:SS bit of the time string
      setText(newRow, 'bgtask-error-row-time', errorDateTime.toTimeString().slice(0, 8));
      setText(
        newRow, 'bgtask-error-row-traceback', BGTaskDetailViewDiv.fixTraceback(newError.traceback)
      );
    }
  }
}

// -------------------------------------------------------------------------------------------------
// Task poller and related functions
// -------------------------------------------------------------------------------------------------
class BGTaskPoller {
  constructor(baseURL) {
    this.baseURL = baseURL;
    this.taskCallbacks = {};
    this.intvl = null;
    this.mostRecentUpdate = null;
  }

  static instances = {};

  static normalizeTask(task) {
    task.updated = new Date(task.updated);

    if (task.completed_at !== null) {
      task.completed_at = new Date(task.completed_at);
      const completedTimeAgoMS = Date.now() - task.completed_at.getTime();
      task.completed_at_time_ago = millisecondsToTimeAgoString(completedTimeAgoMS);
    } else {
      task.completed_at_time_ago = "–";
    }
  }

  static sharedInstance(baseURL) {
    if (BGTaskPoller.instances[baseURL] === undefined) {
      BGTaskPoller.instances[baseURL] = new BGTaskPoller(baseURL);
    }
    return BGTaskPoller.instances[baseURL];
  }

  get numCallbacks() {
    return Object.values(this.taskCallbacks).map(cbks => cbks.length).reduce((a, b) => a + b, 0);
  }

  monitorTask(taskId, cbk) {
    let cbkList = this.taskCallbacks[taskId];
    if (cbkList === undefined) {
      cbkList = [];
      this.taskCallbacks[taskId] = cbkList;
    }
    cbkList.push(cbk);

    this._maybeScheduleNextPoll();
  }

  stopMonitoringTask(taskId, cbk) {
    if (cbk === undefined) {
      this.taskCallbacks[taskId] = [];
      return;
    }

    const cbkList = this.taskCallbacks[taskId];
    if (cbkList === undefined) {
      return;
    }
    const cbkIndex = cbkList.indexOf(cbk);
    if (cbkIndex === -1) {
      return;
    }
    cbkList.splice(cbkIndex, 1);
  }

  _maybeScheduleNextPoll() {
    if (this.intvl !== null || this.numCallbacks === 0) {
      // Not scheduling another poll because either one is in progress or no one is listening.
      return;
    }

    const msToNextRefresh = (
      this.mostRecentUpdate === null
      || (new Date() - this.mostRecentUpdate) < TIME_TO_REDUCED_REFRESH_PERIOD_S * 1000
    ) ? REFRESH_PERIOD_MS : REDUCED_REFRESH_PERIOD_S * 1000;
    this.intvl = setTimeout(() => this._sendPoll(), msToNextRefresh);
  }
  _sendPoll() {
    this.intvl = null;
    const req = new XMLHttpRequest();
    const self = this;
    req.addEventListener("load", function () { self._receivePoll(this); });
    const taskIds = Object.keys(this.taskCallbacks).join(",");
    const url = `${this.baseURL}?tasks=${taskIds}`;
    console.log(`Poll for tasks ${taskIds}`);
    req.open("GET", url);
    req.setRequestHeader('Accept', 'application/json');
    req.send();
  }
  _receivePoll(response) {
    var tasks;
    try {
      tasks = JSON.parse(response.responseText);
    } catch (e) {
      this.stopPolling();
      console.error(e);
      return;
    }

    for (const [taskId, task] of Object.entries(tasks)) {
      BGTaskPoller.normalizeTask(task);

      if (this.mostRecentUpdate === null || task.updated > this.mostRecentUpdate) {
        this.mostRecentUpdate = task.updated;
      }

      for (const cbk of (this.taskCallbacks[task.id] || [])) {
        cbk(task);
      }
      if (task.state !== "running") {
        this.stopMonitoringTask(task.id);
      }
    }

    this._maybeScheduleNextPoll();
  }
  stopPolling() {
    clearInterval(this.intvl);
    this.intvl = null;
  }
}

// -------------------------------------------------------------------------------------------------
// Basic DOM manipulation
// -------------------------------------------------------------------------------------------------
function setText(node, className, text) {
  node.getElementsByClassName(className)[0].textContent = text;
}
function setInnerHTML(node, className, text) {
  node.getElementsByClassName(className)[0].innerHTML = text;
}

function cloneTemplateInto(templateId, contentIdOrEle) {
  const template = document.getElementById(templateId);
  const contentMain = (
    typeof contentIdOrEle === 'string'
    ? document.getElementById(contentIdOrEle)
    : contentIdOrEle
  );
  const clonedNode = template.content.firstElementChild.cloneNode(true);
  contentMain.appendChild(clonedNode);
  return clonedNode;
}
