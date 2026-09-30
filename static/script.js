document.addEventListener("DOMContentLoaded", () => {

    const fileInput = document.getElementById("fileInput");
    const dropZone = document.getElementById("dropZone");
    const fileInfo = document.getElementById("fileInfo");

    const targetSize = document.getElementById("targetSize");
    const unit = document.getElementById("unit");

    const selectBtn = document.getElementById("selectBtn");
    const compressBtn = document.getElementById("compressBtn");
    const clearBtn = document.getElementById("clearBtn");

    const progressArea = document.getElementById("progressArea");
    const progressBar = document.getElementById("progressBar");
    const progressPercent = document.getElementById("progressPercent");
    const progressText = document.getElementById("progressText");

    const result = document.getElementById("result");
    const errorBox = document.getElementById("error");

    let selectedFile = null;


    // -----------------------------
    // FILE SELECT
    // -----------------------------

    selectBtn.addEventListener("click", function () {
    fileInput.click();
});

    fileInput.addEventListener("change", function () {

        if (this.files.length > 0) {
            selectedFile = this.files[0];

            fileInfo.textContent =
                selectedFile.name +
                " (" +
                formatBytes(selectedFile.size) +
                ")";

            dropZone.classList.add("file-selected");
        }
    });


    // -----------------------------
    // DRAG & DROP
    // -----------------------------

    dropZone.addEventListener("dragover", function (e) {
        e.preventDefault();
        dropZone.classList.add("dragover");
    });

    dropZone.addEventListener("dragleave", function () {
        dropZone.classList.remove("dragover");
    });

    dropZone.addEventListener("drop", function (e) {

        e.preventDefault();

        dropZone.classList.remove("dragover");

        if (e.dataTransfer.files.length > 0) {

            selectedFile = e.dataTransfer.files[0];

            fileInput.files = e.dataTransfer.files;

            fileInfo.textContent =
                selectedFile.name +
                " (" +
                formatBytes(selectedFile.size) +
                ")";

            dropZone.classList.add("file-selected");
        }
    });


    // -----------------------------
    // CLEAR BUTTON
    // -----------------------------

    clearBtn.addEventListener("click", function () {

        console.log("Clear button clicked");

        // Clear selected file
        selectedFile = null;

        // Clear file input
        fileInput.value = "";

        // Clear file information
        fileInfo.textContent = "";

        // Reset target size
        targetSize.value = "2";
        unit.value = "MB";

        // Reset progress
        progressBar.style.width = "0%";
        progressPercent.textContent = "0%";
        progressText.textContent = "Ready";

        // Hide progress
        progressArea.classList.add("hidden");

        // Clear result
        result.innerHTML = "";
        result.classList.add("hidden");

        // Clear error
        errorBox.textContent = "";
        errorBox.classList.add("hidden");

        // Remove visual states
        dropZone.classList.remove("dragover");
        dropZone.classList.remove("file-selected");

        // Enable compress button
        compressBtn.disabled = false;

        // Scroll to top
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    });


    // -----------------------------
    // COMPRESS BUTTON
    // -----------------------------

    compressBtn.addEventListener("click", async function () {

        if (!selectedFile) {
            showError("Please select a PDF file first.");
            return;
        }

        if (!targetSize.value || Number(targetSize.value) <= 0) {
            showError("Please enter a valid target size.");
            return;
        }

        if (selectedFile.type !== "application/pdf" &&
            !selectedFile.name.toLowerCase().endsWith(".pdf")) {

            showError("Please select a PDF file.");
            return;
        }

        console.log("Compress button:", compressBtn);

        errorBox.classList.add("hidden");
        result.classList.add("hidden");

        progressArea.classList.remove("hidden");

        compressBtn.disabled = true;

        setProgress(10, "Preparing PDF...");

        const formData = new FormData();

        formData.append("pdf", selectedFile);
        formData.append("target", targetSize.value);
        formData.append("unit", unit.value);

        try {

            setProgress(30, "Compressing PDF...");

            const response = await fetch("/api/compress", {
                method: "POST",
                body: formData
            });

            setProgress(80, "Finalizing...");

            if (!response.ok) {
                let message = "Compression failed.";
                try { const data = await response.json(); message = data.error || message; } catch (_) {}
                throw new Error(message);
            }

            const blob = await response.blob();
            const downloadUrl = URL.createObjectURL(blob);

            // Automatically download the compressed PDF.
            const autoDownloadLink = document.createElement("a");
            autoDownloadLink.href = downloadUrl;
            autoDownloadLink.download = selectedFile.name.replace(/\.pdf$/i, "") + "_compressed.pdf";
            autoDownloadLink.style.display = "none";
            document.body.appendChild(autoDownloadLink);
            autoDownloadLink.click();
            autoDownloadLink.remove();

            const originalSize = Number(response.headers.get("X-Original-Size")) || selectedFile.size;
            const compressedSize = Number(response.headers.get("X-Compressed-Size")) || blob.size;
            const targetBytes = Number(response.headers.get("X-Target-Size")) || 0;
            const mode = response.headers.get("X-Compression-Mode") || "Compression";
            const targetMet = response.headers.get("X-Target-Met") === "true";

            setProgress(100, targetMet ? "Compression completed!" : "Best possible compression completed.");
            result.classList.remove("hidden");
            result.innerHTML = `
                <div class="result-card">
                    <h3>PDF Compressed Successfully</h3>
                    <p>Original Size: <strong>${formatBytes(originalSize)}</strong></p>
                    <p>Compressed Size: <strong>${formatBytes(compressedSize)}</strong></p>
                    <a class="download-btn" href="${downloadUrl}" download="${escapeHtml(selectedFile.name.replace(/\.pdf$/i, ""))}_compressed.pdf">Download Compressed PDF</a>
                </div>`;
        } catch (error) {

            showError(error.message);

        } finally {

            compressBtn.disabled = false;
        }
    });


    // -----------------------------
    // HELPER FUNCTIONS
    // -----------------------------

    function setProgress(percent, text) {

        progressBar.style.width = percent + "%";
        progressPercent.textContent = percent + "%";
        progressText.textContent = text;
    }


    function showError(message) {

        errorBox.textContent = message;
        errorBox.classList.remove("hidden");

        progressArea.classList.add("hidden");
    }


    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    }

    function formatBytes(bytes) {

        if (!bytes || bytes === 0) {
            return "0 Bytes";
        }

        const units = [
            "Bytes",
            "KB",
            "MB"
        ];

        const i = Math.floor(
            Math.log(bytes) / Math.log(1024)
        );

        return (
            (bytes / Math.pow(1024, i)).toFixed(2)
            + " "
            + units[i]
        );
    }

});