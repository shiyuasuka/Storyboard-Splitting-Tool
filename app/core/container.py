from app.project.manager import ProjectManager
from app.services.export_service import ExportService
from app.services.generation_service import GenerationOrchestrator
from app.services.log_service import LogService

project_manager = ProjectManager()
log_service = LogService()
export_service = ExportService()
generation_orchestrator = GenerationOrchestrator(
    project_manager=project_manager,
    log_service=log_service,
    export_service=export_service,
)
