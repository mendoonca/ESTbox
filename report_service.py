from io import BytesIO
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Flask, jsonify, request, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)


def _money(value):
    if value is None or value == "":
        return "-"
    try:
        return f"{Decimal(str(value)):.2f} EUR"
    except (InvalidOperation, ValueError):
        return "-"


def build_vehicle_history_pdf(matricula, revisoes, user_email=None):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "ESTbox - Relatorio de Historico")

    y -= 25
    pdf.setFont("Helvetica", 11)
    pdf.drawString(40, y, f"Matricula: {matricula}")

    if user_email:
        y -= 18
        pdf.drawString(40, y, f"Utilizador: {user_email}")

    y -= 18
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf.drawString(40, y, f"Gerado em: {generated_at}")

    y -= 30
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Data")
    pdf.drawString(120, y, "Descricao")
    pdf.drawString(360, y, "KM")
    pdf.drawString(450, y, "Custo")

    y -= 15
    pdf.line(40, y, width - 40, y)
    y -= 15

    pdf.setFont("Helvetica", 10)

    if not revisoes:
        pdf.drawString(40, y, "Sem manutencoes registadas para este veiculo.")
    else:
        for revisao in revisoes:
            if y < 70:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica-Bold", 10)
                pdf.drawString(40, y, "Data")
                pdf.drawString(120, y, "Descricao")
                pdf.drawString(360, y, "KM")
                pdf.drawString(450, y, "Custo")
                y -= 15
                pdf.line(40, y, width - 40, y)
                y -= 15
                pdf.setFont("Helvetica", 10)

            data = str(revisao.get("data") or "-")
            descricao = str(revisao.get("descricao") or "-")
            descricao = (descricao[:48] + "...") if len(descricao) > 51 else descricao
            km = str(revisao.get("km") or "-")
            custo = _money(revisao.get("custo"))

            pdf.drawString(40, y, data)
            pdf.drawString(120, y, descricao)
            pdf.drawString(360, y, km)
            pdf.drawString(450, y, custo)
            y -= 18

    pdf.save()
    buffer.seek(0)
    return buffer


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/reports/vehicle-history")
def vehicle_history_report():
    payload = request.get_json(silent=True) or {}
    matricula = (payload.get("matricula") or "").strip().upper()
    revisoes = payload.get("revisoes") or []
    user_email = (payload.get("user_email") or "").strip().lower() or None

    if not matricula:
        return jsonify({"error": "matricula obrigatoria"}), 400

    if not isinstance(revisoes, list):
        return jsonify({"error": "revisoes deve ser uma lista"}), 400

    pdf_buffer = build_vehicle_history_pdf(matricula, revisoes, user_email)
    return send_file(
        pdf_buffer,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"historico_{matricula}.pdf"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
