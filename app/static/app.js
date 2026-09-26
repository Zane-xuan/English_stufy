(function () {
  "use strict";

  var toggleBtn = document.getElementById("toggle-btn");
  var transcript = document.getElementById("transcript");

  if (toggleBtn && transcript) {
    var blockEn = transcript.querySelector(".transcript-en");
    var blockZh = transcript.querySelector(".transcript-zh");

    toggleBtn.addEventListener("click", function () {
      var showingEn = !blockEn.hidden;
      blockEn.hidden = showingEn;
      blockZh.hidden = !showingEn;
      toggleBtn.textContent = showingEn ? "显示原文" : "显示译文";
      toggleBtn.dataset.mode = showingEn ? "zh" : "en";
    });
  }

  var items = document.querySelectorAll(".vocab-item");

  function clearHighlights() {
    document.querySelectorAll(".transcript-en mark.term-hit").forEach(function (mark) {
      var parent = mark.parentNode;
      if (!parent) {
        return;
      }
      parent.replaceChild(document.createTextNode(mark.textContent), mark);
      parent.normalize();
    });
  }

  function highlightTerm(term) {
    var root = document.querySelector(".transcript-en");
    if (!root || !term) {
      return;
    }
    var needle = term.toLowerCase();

    root.querySelectorAll("p").forEach(function (paragraph) {
      var walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
      var targets = [];
      var node;
      while ((node = walker.nextNode())) {
        if (node.nodeValue.toLowerCase().indexOf(needle) !== -1) {
          targets.push(node);
        }
      }

      targets.forEach(function (textNode) {
        var text = textNode.nodeValue;
        var lower = text.toLowerCase();
        var fragment = document.createDocumentFragment();
        var cursor = 0;
        var position = lower.indexOf(needle, cursor);

        while (position !== -1) {
          if (position > cursor) {
            fragment.appendChild(document.createTextNode(text.slice(cursor, position)));
          }
          var mark = document.createElement("mark");
          mark.className = "term-hit";
          mark.textContent = text.slice(position, position + term.length);
          fragment.appendChild(mark);
          cursor = position + term.length;
          position = lower.indexOf(needle, cursor);
        }

        if (cursor < text.length) {
          fragment.appendChild(document.createTextNode(text.slice(cursor)));
        }
        textNode.parentNode.replaceChild(fragment, textNode);
      });
    });
  }

  items.forEach(function (item) {
    item.addEventListener("click", function () {
      var wasActive = item.classList.contains("is-active");
      items.forEach(function (other) {
        other.classList.remove("is-active");
      });
      clearHighlights();
      if (wasActive) {
        return;
      }
      item.classList.add("is-active");
      highlightTerm(item.dataset.term || "");
    });
  });

  // 双渠道播放兜底：本地视频加载失败（被清理、下载失败等）时，
  // 自动切到在线嵌入播放，不让用户对着空白播放器发呆。
  var localVideo = document.getElementById("local-media");
  var fallback = document.getElementById("player-fallback");
  if (localVideo && fallback) {
    localVideo.addEventListener("error", function () {
      localVideo.remove();
      fallback.hidden = false;
    });
  }
})();
