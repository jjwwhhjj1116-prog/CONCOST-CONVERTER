/**
 * CONCOST Total Studio - Filee 1.10.2 대시보드 & 사내 인증 & 워크프로세스 컨트롤러
 */

document.addEventListener("DOMContentLoaded", () => {
  // 1. 프로필 및 포맷 데이터 정의 (Filee 180+ 카탈로그)
  const PROFILES = {
    cad: {
      name: "CAD 도면",
      tags: [".pdf", ".dwg", ".dxf", ".step", ".dgn"],
      presets: ["DXF", "DWG", "PDF", "PNG", "SVG"],
      defaultTarget: "DXF",
      desc: "AutoCAD / ZWCAD 호환 표준 벡터 도면",
    },
    documents: {
      name: "문서 / 한글",
      tags: [".hwp", ".hwpx", ".docx", ".pdf", ".txt", ".odt"],
      presets: ["PDF", "DOCX", "HWPX", "TXT", "XLSX"],
      defaultTarget: "PDF",
      desc: "정형 문서 및 텍스트 구조화 파일",
    },
    spreadsheets: {
      name: "표 / 내역서",
      tags: [".xlsx", ".xls", ".csv", ".tsv", ".pdf"],
      presets: ["XLSX", "CSV", "PDF", "HTML"],
      defaultTarget: "XLSX",
      desc: "적산 내역서 및 일람표 셀 복원 엑셀",
    },
    images: {
      name: "이미지",
      tags: [".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".tiff", ".ico"],
      presets: ["WEBP", "PNG", "JPG", "ICO", "BMP", "TIFF"],
      defaultTarget: "WEBP",
      desc: "웹 최적화 고압축 / 무손실 래스터 이미지",
    },
    media_video: {
      name: "동영상",
      tags: [".mp4", ".webm", ".mov", ".mkv", ".avi", ".flv"],
      presets: ["MP4", "MP4 720p", "WEBM", "MOV", "MKV", "GIF"],
      defaultTarget: "MP4",
      desc: "H.264 / AAC 호환 고화질 영상 파일",
    },
    media_audio: {
      name: "오디오",
      tags: [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
      presets: ["MP3", "WAV", "FLAC", "AAC", "OGG"],
      defaultTarget: "MP3",
      desc: "표준 음원 및 고음질 무손실 오디오",
    },
    ebooks: {
      name: "전자책 / 압축",
      tags: [".epub", ".mobi", ".azw3", ".fb2", ".cbz", ".zip"],
      presets: ["AZW3", "FB2", "CBZ", "EPUB", "ZIP"],
      defaultTarget: "AZW3",
      desc: "킨들 / 리더기 전용 전자책 포맷",
    },
    mixed: {
      name: "혼합 파일",
      tags: [".* (모든 파일)"],
      presets: ["ZIP", "PDF", "PNG", "DXF", "XLSX", "MP4"],
      defaultTarget: "ZIP",
      desc: "단일 아카이브 무손실 One ZIP 패킹",
    },
  };

  const ALL_FORMAT_TILES = {
    "CAD / 3D": ["DXF", "DWG", "STEP", "IGES", "DGN", "STL", "OBJ"],
    "문서 / 한글": ["PDF", "DOCX", "HWP", "HWPX", "TXT", "RTF", "ODT", "EPUB"],
    "표 / 스프레드시트": ["XLSX", "CSV", "ODS", "TSV", "HTML"],
    "이미지 / 래스터": ["WEBP", "PNG", "JPG", "JPEG", "ICO", "BMP", "TIFF", "GIF", "HEIC"],
    "동영상 (Video)": ["MP4", "MP4 720p", "WEBM", "MOV", "MKV", "AVI", "WMV", "FLV"],
    "오디오 (Audio)": ["MP3", "WAV", "FLAC", "AAC", "OGG", "M4A", "WMA"],
    "전자책 (E-Books)": ["AZW3", "FB2", "CBZ", "CBR", "MOBI"],
    "압축 (Archives)": ["ZIP", "7Z", "TAR", "GZ", "BZ2"],
  };

  // 애플리케이션 상태
  let currentUser = null;
  let activeProfileKey = "cad";
  let activeTargetFormat = "DXF";
  let stagedFile = null;

  // DOM 캐싱 - 인증 관련
  const loginOverlay = document.getElementById("login-modal-overlay");
  const loginForm = document.getElementById("login-form");
  const loginIdInput = document.getElementById("login-id-input");
  const loginPwdInput = document.getElementById("login-pwd-input");
  const employeeSelect = document.getElementById("employee-select");
  const loginErrorMsg = document.getElementById("login-error-msg");
  const btnTogglePwd = document.getElementById("btn-toggle-pwd");
  const headerUserName = document.getElementById("header-user-name");
  const btnUserMenu = document.getElementById("btn-user-menu");
  const userPopover = document.getElementById("user-popover");
  const popoverUserTitle = document.getElementById("popover-user-title");
  const btnLogout = document.getElementById("btn-logout");

  // 비밀번호 변경 모달
  const pwdModalBackdrop = document.getElementById("pwd-modal-backdrop");
  const btnOpenChangePwd = document.getElementById("btn-open-change-pwd");
  const btnClosePwdModal = document.getElementById("btn-close-pwd-modal");
  const btnCancelPwd = document.getElementById("btn-cancel-pwd");
  const changePwdForm = document.getElementById("change-pwd-form");
  const oldPwdInput = document.getElementById("old-pwd-input");
  const newPwdInput = document.getElementById("new-pwd-input");
  const newPwdConfirm = document.getElementById("new-pwd-confirm");
  const changePwdMsg = document.getElementById("change-pwd-msg");

  // DOM 캐싱 - 대시보드 & 워크프로세스
  const stepIndicator1 = document.getElementById("step-indicator-1");
  const stepIndicator2 = document.getElementById("step-indicator-2");
  const stepIndicator3 = document.getElementById("step-indicator-3");

  const beforeCardContent = document.getElementById("before-card-content");
  const beforeLoadedView = document.getElementById("before-loaded-view");
  const beforeExtBadge = document.getElementById("before-ext-badge");
  const beforeFilename = document.getElementById("before-filename");
  const beforeFilesize = document.getElementById("before-filesize");
  const beforeEngineMatch = document.getElementById("before-engine-match");
  const btnChangeFile = document.getElementById("btn-change-file");

  const donutStage = document.getElementById("donut-stage");
  const donutOrbit = document.getElementById("donut-orbit");
  const donutCenterDrop = document.getElementById("donut-center-drop");
  const donutDropSub = document.getElementById("donut-drop-sub");
  const fileUploader = document.getElementById("file-uploader");
  const selScale = document.getElementById("sel-scale");
  const selDpi = document.getElementById("sel-dpi");

  const afterTargetBadge = document.getElementById("after-target-badge");
  const afterTargetDesc = document.getElementById("after-target-desc");
  const btnRunConvert = document.getElementById("btn-run-convert");
  const actionHint = document.getElementById("action-hint");

  const profileTabs = document.querySelectorAll(".profile-tabs-bar .tab-item[data-profile]");
  const extTagsContainer = document.getElementById("ext-tags-container");
  const tilesGrid = document.getElementById("tiles-grid");
  const formatSearchInput = document.getElementById("format-search-input");
  const progressCardsGrid = document.getElementById("progress-cards-grid");
  const queueStatusText = document.getElementById("queue-status-text");
  const btnClearQueue = document.getElementById("btn-clear-queue");

  // =========================================================================
  // 1. 임직원 로그인 시스템 초기화 및 ZWCAD 가속 확인
  // =========================================================================
  initAuth();
  checkZwcadStatus();

  async function checkZwcadStatus() {
    const zwBadge = document.getElementById("zwcad-status-badge");
    const zwText = document.getElementById("zwcad-status-text");
    if (!zwBadge || !zwText) return;

    try {
      const res = await fetch("/api/cad/zwcad-status");
      const data = await res.json();
      if (data.available && data.versions && data.versions.length > 0) {
        const topVer = data.versions[0].replace("ZWCAD.Application.", "ZWCAD ");
        zwText.textContent = `⚡ ${topVer} DWG 연동`;
        zwBadge.style.borderColor = "rgba(56, 189, 248, 0.6)";
        zwBadge.title = `CONCOST-Converter ZWCAD 가속 연동: ${data.versions.join(", ")}`;
      } else {
        zwText.textContent = "📐 DXF 정밀 벡터";
        zwBadge.style.borderColor = "rgba(148, 163, 184, 0.3)";
        zwBadge.title = "AutoCAD 표준 DXF 정밀 벡터 모드";
      }
    } catch (e) {
      zwText.textContent = "📐 DXF 정밀 모드";
    }
  }

  function initAuth() {
    // 저장된 세션 검사
    const savedUser = localStorage.getItem("concost_converter_user");
    if (savedUser) {
      try {
        currentUser = JSON.parse(savedUser);
        onLoginSuccess(currentUser, false);
      } catch (e) {
        localStorage.removeItem("concost_converter_user");
      }
    }

    // 서버에서 117명 임직원 목록 조회하여 드롭다운 채우기
    fetch("/api/auth/employees")
      .then((r) => r.json())
      .then((data) => {
        if (data.employees && data.employees.length > 0) {
          employeeSelect.innerHTML = `<option value="">-- 임직원(${data.employees.length}명) 선택 시 자동입력 --</option>`;
          data.employees.forEach((emp) => {
            const opt = document.createElement("option");
            opt.value = emp.login_id;
            opt.textContent = `[${emp.department}] ${emp.name} ${emp.rank} (${emp.login_id})`;
            employeeSelect.appendChild(opt);
          });
        }
      })
      .catch((err) => console.log("임직원 목록 로드 대기:", err));

    // 빠른 계정 선택 칩 버튼
    document.querySelectorAll(".chip-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        loginIdInput.value = btn.dataset.id;
        loginPwdInput.value = "1234";
      });
    });

    // 드롭다운 선택 시 아이디 자동 입력
    employeeSelect.addEventListener("change", (e) => {
      if (e.target.value) {
        loginIdInput.value = e.target.value;
        loginPwdInput.value = "1234";
      }
    });

    // 비밀번호 표시 토글
    btnTogglePwd.addEventListener("click", () => {
      loginPwdInput.type = loginPwdInput.type === "password" ? "text" : "password";
      btnTogglePwd.textContent = loginPwdInput.type === "password" ? "👁" : "🔒";
    });

    // 로그인 폼 제출
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      loginErrorMsg.classList.add("hidden");

      const lid = loginIdInput.value.trim();
      const pwd = loginPwdInput.value.trim();

      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ login_id: lid, password: pwd }),
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || "로그인 실패");
        }

        const data = await res.json();
        currentUser = data.user;
        localStorage.setItem("concost_converter_user", JSON.stringify(currentUser));
        onLoginSuccess(currentUser, true);
      } catch (err) {
        loginErrorMsg.textContent = err.message;
        loginErrorMsg.classList.remove("hidden");
      }
    });

    // 사용자 프로필 메뉴 열기/닫기
    btnUserMenu.addEventListener("click", (e) => {
      e.stopPropagation();
      userPopover.classList.toggle("hidden");
    });
    document.addEventListener("click", () => userPopover.classList.add("hidden"));

    // 로그아웃
    btnLogout.addEventListener("click", () => {
      localStorage.removeItem("concost_converter_user");
      currentUser = null;
      loginOverlay.classList.remove("hidden");
      userPopover.classList.add("hidden");
      headerUserName.textContent = "로그인 대기";
    });

    // 비밀번호 변경 모달 열기/닫기
    btnOpenChangePwd.addEventListener("click", () => {
      userPopover.classList.add("hidden");
      pwdModalBackdrop.classList.remove("hidden");
      oldPwdInput.value = "";
      newPwdInput.value = "";
      newPwdConfirm.value = "";
      changePwdMsg.classList.add("hidden");
    });

    const closePwdModal = () => pwdModalBackdrop.classList.add("hidden");
    btnClosePwdModal.addEventListener("click", closePwdModal);
    btnCancelPwd.addEventListener("click", closePwdModal);

    // 비밀번호 변경 제출
    changePwdForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      changePwdMsg.classList.add("hidden");

      if (newPwdInput.value !== newPwdConfirm.value) {
        changePwdMsg.textContent = "새 비밀번호가 일치하지 않습니다.";
        changePwdMsg.classList.remove("hidden");
        return;
      }

      try {
        const res = await fetch("/api/auth/change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            login_id: currentUser.login_id,
            old_password: oldPwdInput.value,
            new_password: newPwdInput.value,
          }),
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "변경 실패");
        }
        alert("비밀번호가 성공적으로 변경되었습니다.");
        closePwdModal();
      } catch (err) {
        changePwdMsg.textContent = err.message;
        changePwdMsg.classList.remove("hidden");
      }
    });
  }

  function onLoginSuccess(user, isNewLogin) {
    loginOverlay.classList.add("hidden");
    headerUserName.textContent = `${user.name} ${user.rank} (${user.department})`;
    popoverUserTitle.textContent = `${user.name} ${user.rank} (${user.login_id})`;
  }

  // =========================================================================
  // 2. [Before ➔ Transform ➔ After] 3단계 워크프로세스 초기화
  // =========================================================================
  initProfile(activeProfileKey);
  renderAllFormatTiles();

  // 프로필 탭 전환 이벤트
  profileTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      profileTabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      activeProfileKey = tab.dataset.profile;
      initProfile(activeProfileKey);
    });
  });

  function initProfile(profileKey) {
    const prof = PROFILES[profileKey];
    if (!prof) return;

    activeTargetFormat = prof.defaultTarget;
    updateAfterTargetDisplay(activeTargetFormat, prof.desc);
    renderExtTags(prof.tags);
    renderDonutOrbit(prof.presets);
  }

  function updateAfterTargetDisplay(targetFmt, customDesc = null) {
    afterTargetBadge.textContent = targetFmt.toUpperCase();
    if (customDesc) {
      afterTargetDesc.textContent = customDesc;
    } else if (targetFmt.toUpperCase() === "DWG") {
      afterTargetDesc.textContent = "CONCOST ZWCAD COM 가속 바이너리 DWG 생성 & 재열기 무결성 검증";
    } else if (targetFmt.toUpperCase() === "DXF") {
      afterTargetDesc.textContent = "CONCOST 3차 베지어 곡선 적응형 분할 & 건축 레이어 분리 R2013 DXF";
    } else {
      afterTargetDesc.textContent = `고품질 표준 ${targetFmt.toUpperCase()} 파일로 변환`;
    }
  }

  // 확장자 태그 렌더링
  function renderExtTags(tags) {
    extTagsContainer.innerHTML = "";
    tags.forEach((tag) => {
      const span = document.createElement("span");
      span.className = "ext-tag";
      span.innerHTML = `${tag} <button class="btn-remove-tag">×</button>`;
      span.querySelector(".btn-remove-tag").addEventListener("click", () => span.remove());
      extTagsContainer.appendChild(span);
    });

    const addBtn = document.createElement("button");
    addBtn.className = "btn-add-tag";
    addBtn.textContent = "+ 확장자 추가";
    addBtn.addEventListener("click", () => {
      const newTag = prompt("추가할 확장자를 입력하세요 (예: .dwg, .pdf):");
      if (newTag) {
        const dotTag = newTag.startsWith(".") ? newTag : `.${newTag}`;
        renderExtTags([...tags, dotTag]);
      }
    });
    extTagsContainer.appendChild(addBtn);
  }

  // 도넛 원형 궤도 렌더링
  function renderDonutOrbit(presets) {
    donutOrbit.innerHTML = "";
    const total = presets.length;
    const radius = 145; // 궤도 반지름
    const centerX = 145;
    const centerY = 145;

    presets.forEach((fmt, index) => {
      const angle = (index / total) * 2 * Math.PI - Math.PI / 2;
      const x = centerX + radius * Math.cos(angle);
      const y = centerY + radius * Math.sin(angle);

      const badge = document.createElement("div");
      badge.className = `orbit-badge ${fmt.toUpperCase() === activeTargetFormat.toUpperCase() ? "active" : ""}`;
      badge.textContent = fmt;
      badge.style.left = `${x}px`;
      badge.style.top = `${y}px`;

      badge.addEventListener("click", () => {
        document.querySelectorAll(".orbit-badge").forEach((b) => b.classList.remove("active"));
        badge.classList.add("active");
        activeTargetFormat = fmt;
        updateAfterTargetDisplay(fmt);
        advanceToStep(2);
      });

      // 뱃지 위에 직접 드롭 시 해당 포맷으로 즉시 실행!
      badge.addEventListener("dragover", (e) => {
        e.preventDefault();
        badge.classList.add("active");
      });
      badge.addEventListener("dragleave", () => {
        if (fmt.toUpperCase() !== activeTargetFormat.toUpperCase()) badge.classList.remove("active");
      });
      badge.addEventListener("drop", (e) => {
        e.preventDefault();
        e.stopPropagation();
        activeTargetFormat = fmt;
        updateAfterTargetDisplay(fmt);
        const files = e.dataTransfer.files;
        if (files.length > 0) {
          handleFileStaged(files[0]);
          executeConversion(files[0], fmt);
        }
      });

      donutOrbit.appendChild(badge);
    });
  }

  // 우측 포맷 타일 팔레트 렌더링
  function renderAllFormatTiles(filterQuery = "") {
    tilesGrid.innerHTML = "";
    const q = filterQuery.toLowerCase().trim();

    Object.entries(ALL_FORMAT_TILES).forEach(([category, tiles]) => {
      const filtered = tiles.filter((t) => t.toLowerCase().includes(q));
      if (filtered.length === 0) return;

      const group = document.createElement("div");
      group.className = "tile-category-group";

      const h4 = document.createElement("h4");
      h4.textContent = category;
      group.appendChild(h4);

      const grid = document.createElement("div");
      grid.className = "tile-grid";

      filtered.forEach((tileName) => {
        const tile = document.createElement("div");
        tile.className = `format-tile ${tileName.toUpperCase() === activeTargetFormat.toUpperCase() ? "selected" : ""}`;
        tile.textContent = tileName;

        tile.addEventListener("click", () => {
          document.querySelectorAll(".format-tile").forEach((t) => t.classList.remove("selected"));
          tile.classList.add("selected");
          activeTargetFormat = tileName;
          updateAfterTargetDisplay(tileName);
          advanceToStep(2);

          // 도넛 궤도 반영
          document.querySelectorAll(".orbit-badge").forEach((b) => {
            if (b.textContent.trim().toUpperCase() === tileName.toUpperCase()) b.classList.add("active");
            else b.classList.remove("active");
          });
        });

        grid.appendChild(tile);
      });

      group.appendChild(grid);
      tilesGrid.appendChild(group);
    });
  }

  formatSearchInput.addEventListener("input", (e) => renderAllFormatTiles(e.target.value));

  // =========================================================================
  // 3. 파일 드롭 및 Before 상태 렌더링
  // =========================================================================
  donutCenterDrop.addEventListener("click", () => fileUploader.click());

  donutCenterDrop.addEventListener("dragover", (e) => {
    e.preventDefault();
    donutCenterDrop.classList.add("dragover");
  });

  donutCenterDrop.addEventListener("dragleave", () => donutCenterDrop.classList.remove("dragover"));

  donutCenterDrop.addEventListener("drop", (e) => {
    e.preventDefault();
    donutCenterDrop.classList.remove("dragover");
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileStaged(files[0]);
    }
  });

  fileUploader.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFileStaged(e.target.files[0]);
    }
  });

  btnChangeFile.addEventListener("click", () => {
    stagedFile = null;
    fileUploader.value = "";
    document.querySelector(".empty-placeholder").classList.remove("hidden");
    beforeLoadedView.classList.add("hidden");
    donutDropSub.textContent = "여기에 파일을 놓으세요";
    btnRunConvert.disabled = true;
    actionHint.textContent = "※ 먼저 왼쪽(또는 도넛)에 파일을 넣어주세요";
    advanceToStep(1);
  });

  function handleFileStaged(file) {
    stagedFile = file;
    const ext = file.name.split(".").pop().toUpperCase();
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);

    // 1. [BEFORE] 카드 뷰 업데이트
    document.querySelector(".empty-placeholder").classList.add("hidden");
    beforeLoadedView.classList.remove("hidden");
    beforeExtBadge.textContent = ext;
    beforeFilename.textContent = file.name;
    beforeFilesize.textContent = `${sizeMb} MB (${(file.size / 1024).toFixed(1)} KB)`;

    // 확장자별 추천 엔진 매칭
    if (ext === "PDF") {
      beforeEngineMatch.textContent = "✓ 도면(DXF) / 내역서(Excel) 엔진 준비됨";
      // CAD 프로필 자동 제안
      document.querySelector('[data-profile="cad"]').click();
    } else if (["PNG", "JPG", "JPEG", "WEBP", "BMP"].includes(ext)) {
      beforeEngineMatch.textContent = "✓ 고해상도 이미지 변환 엔진 준비됨";
      document.querySelector('[data-profile="images"]').click();
    } else if (["HWP", "HWPX", "DOCX", "TXT"].includes(ext)) {
      beforeEngineMatch.textContent = "✓ 한글 및 오피스 문서 엔진 준비됨";
      document.querySelector('[data-profile="documents"]').click();
    } else {
      beforeEngineMatch.textContent = "✓ 범용 다단계 변환 파이프라인 매칭";
    }

    donutDropSub.textContent = `선택됨: ${file.name}`;

    // 2. [AFTER] 실행 버튼 활성화
    btnRunConvert.disabled = false;
    actionHint.textContent = `클릭 시 [${ext} ➔ ${activeTargetFormat}] 변환이 즉시 시작됩니다`;

    advanceToStep(2);
  }

  function advanceToStep(stepNum) {
    stepIndicator1.classList.remove("active");
    stepIndicator2.classList.remove("active");
    stepIndicator3.classList.remove("active");

    if (stepNum === 1) stepIndicator1.classList.add("active");
    else if (stepNum === 2) stepIndicator2.classList.add("active");
    else if (stepNum === 3) stepIndicator3.classList.add("active");
  }

  // =========================================================================
  // 4. [AFTER] 변환 실행 및 실시간 카드 큐 렌더링
  // =========================================================================
  btnRunConvert.addEventListener("click", () => {
    if (!stagedFile) return;
    executeConversion(stagedFile, activeTargetFormat);
  });

  function executeConversion(file, targetFmt) {
    advanceToStep(3);
    const taskId = `task-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
    const ext = file.name.split(".").pop().toUpperCase();
    const target = targetFmt.toUpperCase();

    // 실시간 진행 카드 생성
    const card = document.createElement("div");
    card.className = "conversion-card";
    card.id = taskId;

    card.innerHTML = `
      <div class="card-top">
        <div class="card-file-info">
          <span class="card-icon">⚡</span>
          <div class="card-names">
            <div class="card-title" title="${file.name}">${file.name}</div>
            <div class="card-route">${ext} ➔ ${target}</div>
          </div>
        </div>
        <span class="card-status-badge converting">변환 중...</span>
      </div>
      <div class="card-progress-bar-bg">
        <div class="card-progress-bar-fill" style="width: 20%"></div>
      </div>
      <div class="card-footer">
        <span class="card-meta">${(file.size / 1024).toFixed(1)} KB · 엔진 작업 큐 할당</span>
        <div class="card-actions"></div>
      </div>
    `;

    progressCardsGrid.prepend(card);
    queueStatusText.textContent = `작업 처리 중: ${file.name}`;

    const fillEl = card.querySelector(".card-progress-bar-fill");
    const statusEl = card.querySelector(".card-status-badge");
    const metaEl = card.querySelector(".card-meta");
    const actionsEl = card.querySelector(".card-actions");

    let p = 25;
    const timer = setInterval(() => {
      if (p < 85) {
        p += Math.floor(Math.random() * 18) + 5;
        fillEl.style.width = `${p}%`;
      }
    }, 150);

    // API 요청 구성
    const formData = new FormData();
    formData.append("file", file);
    formData.append("target_format", target.toLowerCase());

    const scaleVal = selScale.value;
    if (scaleVal === "auto") {
      formData.append("auto_detect_scale", "true");
      formData.append("scale_multiplier", "1.0");
    } else {
      formData.append("auto_detect_scale", "false");
      formData.append("scale_multiplier", scaleVal);
    }
    formData.append("dpi", selDpi.value);

    const startTime = performance.now();

    fetch("/api/convert", {
      method: "POST",
      body: formData,
    })
      .then((res) => {
        clearInterval(timer);
        if (!res.ok) throw new Error("서버 변환 실패");
        return res.json();
      })
      .then((data) => {
        const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
        fillEl.style.width = "100%";
        card.classList.add("done");
        statusEl.className = "card-status-badge success";
        statusEl.textContent = "변환 완료";

        let engineDesc = "Total Core";
        if (data.metadata && data.metadata.engine) engineDesc = data.metadata.engine;
        metaEl.textContent = `${(data.file_size_bytes / 1024).toFixed(1)} KB · ${elapsed}초 · ${engineDesc}`;

        actionsEl.innerHTML = `
          <a href="${data.download_url}" download class="card-btn-download">다운로드 ➔</a>
        `;
        queueStatusText.textContent = "변환 완료";
      })
      .catch((err) => {
        clearInterval(timer);
        fillEl.style.width = "100%";
        fillEl.style.background = "var(--accent-red)";
        statusEl.className = "card-status-badge";
        statusEl.style.background = "rgba(239, 68, 68, 0.2)";
        statusEl.style.color = "#f87171";
        statusEl.textContent = "실패";
        metaEl.textContent = `오류 발생: ${err.message}`;
        queueStatusText.textContent = "오류 발생";
      });
  }

  btnClearQueue.addEventListener("click", () => {
    progressCardsGrid.innerHTML = "";
    queueStatusText.textContent = "대기열 비워짐";
  });
});
