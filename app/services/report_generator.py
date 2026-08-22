import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.colors import HexColor

class PDFReportGenerator:
    def __init__(self, output_dir: str = "./data/reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=HexColor('#0f172a'),
            spaceAfter=20,
        ))
        self.styles.add(ParagraphStyle(
            name='RiskHigh',
            parent=self.styles['Normal'],
            textColor=HexColor('#ef4444'),
            fontName='Helvetica-Bold',
        ))

    def generate_incident_report(self, incident_data: dict) -> str:
        """
        Generate a PDF compliance/incident report.
        Returns the absolute path to the generated PDF.
        """
        factory_id = incident_data.get('factory_id', 'unknown')
        incident_id = incident_data.get('incident_id', f'inc_{int(datetime.now().timestamp())}')
        
        filename = f"incident_{factory_id}_{incident_id}.pdf"
        filepath = os.path.abspath(os.path.join(self.output_dir, filename))
        
        doc = SimpleDocTemplate(filepath, pagesize=letter)
        story = []
        
        # Title
        story.append(Paragraph(f"Safety Incident Report: {factory_id}", self.styles['ReportTitle']))
        
        # Date & Time
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"<b>Generated:</b> {timestamp}", self.styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Incident Details
        story.append(Paragraph("<b>Incident Details</b>", self.styles['Heading2']))
        story.append(Paragraph(incident_data.get('description', 'No description provided.'), self.styles['Normal']))
        story.append(Spacer(1, 12))
        
        # Risk Factors
        story.append(Paragraph("<b>Risk Analysis</b>", self.styles['Heading2']))
        risk_score = incident_data.get('risk_score', 0.0)
        risk_style = self.styles['RiskHigh'] if risk_score > 0.6 else self.styles['Normal']
        story.append(Paragraph(f"Calculated Risk Score: {risk_score}", risk_style))
        
        for factor in incident_data.get('risk_factors', []):
            story.append(Paragraph(f"• {factor}", self.styles['Normal']))
            
        story.append(Spacer(1, 12))
        
        # Interventions
        story.append(Paragraph("<b>Recommended Interventions</b>", self.styles['Heading2']))
        for inv in incident_data.get('interventions', []):
            story.append(Paragraph(f"• {inv}", self.styles['Normal']))
            
        # Build PDF
        doc.build(story)
        return filepath
