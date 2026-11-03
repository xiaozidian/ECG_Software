"""Forbid actual PDF generation while retaining mocked JS print guard tests."""
def pytest_configure(config):
 import app
 from ecg_core import report_pdf,report_paper_pdf
 def forbidden(*a,**k):raise AssertionError('Actual PDF generation is forbidden in UI-only Windows verification')
 app.build_report_pdf=forbidden
 report_pdf.build_report_pdf=forbidden
 report_paper_pdf.build_paper_pdf=forbidden
