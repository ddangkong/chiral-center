import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useDocumentStore } from './document'
import { useSimulationStore } from './simulation'
import { useReportStore } from './report'

// ── Types ─────────────────────────────────────────────

export interface ProjectDoc {
  id: string
  name: string
  ext: string
  size: string
  pages: string
  chunks: number
}

export interface OntologyVersion {
  id: string
  version: number
  createdAt: string
  model: string
  provider: string
  nodeCount: number
  edgeCount: number
  entityCount: number
  relationCount: number
  docIds: string[]
  topic: string
  purpose: string
  label?: string
}

export interface SimulationVersion {
  id: string
  version: number
  ontologyId: string
  createdAt: string
  model: string
  provider: string
  rounds: number
  agentCount: number
  topic: string
}

export interface ReportVersion {
  id: string
  version: number
  simulationId: string
  ontologyId: string
  createdAt: string
  model: string
  provider: string
  sectionCount: number
  title: string
  sections: { title: string; content: string; order: number }[]
  markdown: string
}

export interface Project {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  documents: ProjectDoc[]
  ontologies: OntologyVersion[]
  simulations: SimulationVersion[]
  reports: ReportVersion[]
  activeOntologyId?: string
  activeSimulationId?: string
  activeReportId?: string
  dbId: string | null  // 연결된 DB 컬렉션 ID
  dbPrompted: boolean  // DB 연동 팝업을 이미 표시했는지 여부
}

// ── Store ──────────────────────────────────────────────

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const currentProjectId = ref<string>('')

  watch(projects, (list) => {
    for (const project of list) {
      if (project.dbId === undefined) project.dbId = null
      if (project.dbPrompted === undefined) project.dbPrompted = false
      delete (project as Project & { useDb?: unknown }).useDb
      delete (project as Project & { dbFiles?: unknown }).dbFiles
    }
  }, { deep: true, immediate: true })

  // ── Getters ────────────────────────────────────────

  const currentProject = computed(() =>
    projects.value.find(p => p.id === currentProjectId.value) ?? null
  )

  const activeOntology = computed(() => {
    const p = currentProject.value
    if (!p) return null
    if (p.activeOntologyId) return p.ontologies.find(o => o.id === p.activeOntologyId) ?? p.ontologies.at(-1) ?? null
    return p.ontologies.at(-1) ?? null
  })

  const activeSimulation = computed(() => {
    const p = currentProject.value
    if (!p) return null
    if (p.activeSimulationId) return p.simulations.find(s => s.id === p.activeSimulationId) ?? p.simulations.at(-1) ?? null
    return p.simulations.at(-1) ?? null
  })

  const activeReport = computed(() => {
    const p = currentProject.value
    if (!p) return null
    if (p.activeReportId) return p.reports.find(r => r.id === p.activeReportId) ?? p.reports.at(-1) ?? null
    return p.reports.at(-1) ?? null
  })

  const canRunOntology  = computed(() => (currentProject.value?.documents.length ?? 0) > 0)
  const canRunSimulation = computed(() => (currentProject.value?.ontologies.length ?? 0) > 0)
  const canRunReport     = computed(() => (currentProject.value?.simulations.length ?? 0) > 0)

  // 활성 온톨로지에 속한 시뮬레이션만
  const activeOntologySimulations = computed(() => {
    const p = currentProject.value
    if (!p) return []
    const ontoId = p.activeOntologyId ?? p.ontologies.at(-1)?.id
    if (!ontoId) return p.simulations
    return p.simulations.filter(s => s.ontologyId === ontoId)
  })

  // 활성 시뮬레이션에 속한 보고서만
  const activeSimulationReports = computed(() => {
    const p = currentProject.value
    if (!p) return []
    const simId = p.activeSimulationId ?? p.simulations.at(-1)?.id
    if (!simId) return p.reports
    return p.reports.filter(r => r.simulationId === simId)
  })

  // ── Actions ────────────────────────────────────────

  function createProject(doc: ProjectDoc): Project {
    const project: Project = {
      id: doc.id,
      name: doc.name.replace(/\.[^.]+$/, ''),
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      documents: [doc],
      ontologies: [],
      simulations: [],
      reports: [],
      dbId: null,
      dbPrompted: false,
    }
    projects.value.unshift(project)
    currentProjectId.value = project.id
    return project
  }

  function startNewProject() {
    // 현재 프로젝트 시뮬레이션 데이터 저장
    if (currentProjectId.value) {
      const simStore = useSimulationStore()
      simStore.saveToProject(currentProjectId.value)
    }
    // Clear current selection — next upload creates a new project
    currentProjectId.value = ''
    // 문서·추출 상태 초기화 (리서치 세션은 유지)
    const docStore = useDocumentStore()
    docStore.resetForNewProject()
    // 시뮬레이션 상태 초기화
    const simStore = useSimulationStore()
    simStore.resetAll()
  }

  function setCurrentProject(id: string) {
    // 이전 프로젝트 시뮬레이션 데이터 저장
    if (currentProjectId.value) {
      const simStore = useSimulationStore()
      simStore.saveToProject(currentProjectId.value)
    }

    currentProjectId.value = id
    const project = projects.value.find(p => p.id === id)
    if (!project) return

    // 1. 문서·온톨로지 동기화
    const docStore = useDocumentStore()
    const activeOntoId = project.activeOntologyId ?? project.ontologies[project.ontologies.length - 1]?.id
    docStore.syncWithProject(project.documents, activeOntoId)

    // 2. 시뮬레이션 데이터 복원 (localStorage에서)
    const simStore = useSimulationStore()
    simStore.loadFromProject(id)

    // 3. 활성 리포트 복원
    const reportStore = useReportStore()
    const activeReportId = project.activeReportId
    if (activeReportId) {
      const rv = project.reports.find(r => r.id === activeReportId)
      if (rv) reportStore.loadVersion(rv)
    } else if (project.reports.length > 0) {
      reportStore.loadVersion(project.reports[project.reports.length - 1])
    }
  }

  function addDocumentToCurrentProject(doc: ProjectDoc) {
    const p = currentProject.value
    if (!p) return
    if (!p.documents.find(d => d.id === doc.id)) {
      p.documents.push(doc)
      p.updatedAt = new Date().toISOString()
    }
  }

  function addOntologyVersion(opts: {
    id: string
    nodeCount: number
    edgeCount: number
    entityCount: number
    relationCount: number
    topic: string
    purpose: string
    model: string
    provider: string
    docIds: string[]
  }): OntologyVersion | null {
    const p = currentProject.value
    if (!p) return null

    const version = p.ontologies.length + 1
    const onto: OntologyVersion = {
      id: opts.id,
      version,
      createdAt: new Date().toISOString(),
      model: opts.model,
      provider: opts.provider,
      nodeCount: opts.nodeCount,
      edgeCount: opts.edgeCount,
      entityCount: opts.entityCount,
      relationCount: opts.relationCount,
      docIds: opts.docIds,
      topic: opts.topic,
      purpose: opts.purpose,
    }
    p.ontologies.push(onto)
    p.activeOntologyId = onto.id
    p.updatedAt = new Date().toISOString()
    return onto
  }

  function addSimulationVersion(opts: {
    id: string
    topic: string
    rounds: number
    agentCount: number
    model: string
    provider: string
    ontologyId: string
  }): SimulationVersion | null {
    const p = currentProject.value
    if (!p) return null

    const version = p.simulations.length + 1
    const sim: SimulationVersion = {
      id: opts.id,
      version,
      ontologyId: opts.ontologyId,
      createdAt: new Date().toISOString(),
      model: opts.model,
      provider: opts.provider,
      rounds: opts.rounds,
      agentCount: opts.agentCount,
      topic: opts.topic,
    }
    p.simulations.push(sim)
    p.activeSimulationId = sim.id
    p.updatedAt = new Date().toISOString()
    return sim
  }

  function addReportVersion(opts: {
    id: string
    title: string
    sectionCount: number
    model: string
    provider: string
    simulationId: string
    ontologyId: string
    sections: { title: string; content: string; order: number }[]
    markdown: string
  }): ReportVersion | null {
    const p = currentProject.value
    if (!p) return null

    const version = p.reports.length + 1
    const rep: ReportVersion = {
      id: opts.id,
      version,
      simulationId: opts.simulationId,
      ontologyId: opts.ontologyId,
      createdAt: new Date().toISOString(),
      model: opts.model,
      provider: opts.provider,
      sectionCount: opts.sectionCount,
      title: opts.title,
      sections: opts.sections,
      markdown: opts.markdown,
    }
    p.reports.push(rep)
    p.activeReportId = rep.id
    p.updatedAt = new Date().toISOString()
    return rep
  }

  function setActiveOntology(ontologyId: string) {
    const p = currentProject.value
    if (!p) return
    p.activeOntologyId = ontologyId
    // docStore 온톨로지 ID 동기화 → OntologyView에서 그래프 자동 로드
    const docStore = useDocumentStore()
    docStore.ontologyId = ontologyId
    // cascade → 이 온톨로지의 최신 시뮬레이션
    const relatedSims = p.simulations.filter(s => s.ontologyId === ontologyId)
    const latestSim = relatedSims.at(-1)
    p.activeSimulationId = latestSim?.id
    // cascade → 그 시뮬레이션의 최신 보고서
    if (latestSim) {
      const relatedReps = p.reports.filter(r => r.simulationId === latestSim.id)
      p.activeReportId = relatedReps.at(-1)?.id
    } else {
      p.activeReportId = undefined
    }
  }

  function setActiveSimulation(simulationId: string) {
    const p = currentProject.value
    if (!p) return
    p.activeSimulationId = simulationId
    // cascade → 이 시뮬레이션의 최신 보고서
    const relatedReps = p.reports.filter(r => r.simulationId === simulationId)
    p.activeReportId = relatedReps.at(-1)?.id
  }

  function setActiveReport(reportId: string) {
    const p = currentProject.value
    if (p) p.activeReportId = reportId
  }

  function removeDocument(docId: string) {
    const p = currentProject.value
    if (!p) return
    p.documents = p.documents.filter(d => d.id !== docId)
    p.updatedAt = new Date().toISOString()
  }

  function deleteOntologyVersion(ontologyId: string) {
    const p = currentProject.value
    if (!p) return
    // Cascade: collect orphaned sim IDs
    const orphanSimIds = p.simulations.filter(s => s.ontologyId === ontologyId).map(s => s.id)
    p.simulations = p.simulations.filter(s => s.ontologyId !== ontologyId)
    p.reports = p.reports.filter(r => !orphanSimIds.includes(r.simulationId))
    p.ontologies = p.ontologies.filter(o => o.id !== ontologyId)
    if (p.activeOntologyId === ontologyId) p.activeOntologyId = p.ontologies.at(-1)?.id
    p.updatedAt = new Date().toISOString()
  }

  function setProjectDb(projectId: string, dbId: string | null) {
    const p = projects.value.find(pr => pr.id === projectId)
    if (p) {
      p.dbId = dbId
      p.dbPrompted = true
      p.updatedAt = new Date().toISOString()
    }
  }

  function deleteProject(projectId: string) {
    projects.value = projects.value.filter(p => p.id !== projectId)
    // 저장된 시뮬레이션 데이터도 정리
    const simStore = useSimulationStore()
    simStore.removeProjectData(projectId)
    if (currentProjectId.value === projectId) {
      currentProjectId.value = projects.value[0]?.id ?? ''
    }
  }

  function fmtDate(iso: string) {
    const d = new Date(iso)
    return `${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
  }

  return {
    projects, currentProjectId,
    currentProject, activeOntology, activeSimulation, activeReport,
    activeOntologySimulations, activeSimulationReports,
    canRunOntology, canRunSimulation, canRunReport,
    createProject, startNewProject, setCurrentProject,
    addDocumentToCurrentProject,
    addOntologyVersion, addSimulationVersion, addReportVersion,
    setActiveOntology, setActiveSimulation, setActiveReport,
    removeDocument, deleteOntologyVersion, deleteProject,
    setProjectDb,
    fmtDate,
  }
}, {
  persist: ({
    afterRestore: (ctx: any) => {
      // 구버전 localStorage 데이터 마이그레이션: useDb/dbFiles → dbId
      ctx.store.projects.forEach((p: any) => {
        if (p.dbId === undefined) p.dbId = null
        if (p.dbPrompted === undefined) p.dbPrompted = false
        delete p.useDb
        delete p.dbFiles
      })
    },
  } as any),
})
