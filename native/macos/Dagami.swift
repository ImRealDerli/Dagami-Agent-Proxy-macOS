import SwiftUI
import AppKit

let designTest = Bundle.main.object(forInfoDictionaryKey:"DagamiDesignTest") as? Bool == true

struct Profile: Decodable, Identifiable {
    var id:String; var name:String; var dns:Bool; var proxy:Bool; var endpoints:[String]; var scope:String; var domains:[String]
    var subtitle:String { dns ? (proxy ? "Smart DNS + прокси" : "Smart DNS · без прокси") : (proxy ? "Прокси" : "Обычная сеть") }
}
struct ProfileDetails:Decodable {var name:String;var url:String;var proxy:Bool;var dns:Bool;var endpoints:[String];var scope:String;var domains:[String]}
struct ProfileEditorTarget:Identifiable {let id=UUID();var profile:Profile?}
struct ClientApp: Decodable, Identifiable { var id:String;var name:String;var path:String;var installed:Bool;var prepared:Bool;var launchError:String?;var preparationError:String?=nil;var recoverable:Bool?=nil }
struct NetworkService:Decodable,Identifiable { var id:String;var name:String }
struct Snapshot:Decodable {
    var profiles:[Profile]=[];var apps:[ClientApp]=[];var services:[NetworkService]=[]
    var networkEngine:String?=nil;var monitoring:Bool?=true;var desktopMonitoring:Bool?=false;var systemDNS:String="Нет данных";var activated:Bool=false;var startup:Bool=false;var providers:[String:[String]]=[:]
}
struct UpdateInfo:Codable {
    var available:Bool=false;var current:String="";var currentBuild:Int=0;var tag:String="";var url:String="https://github.com/ImRealDerli/Dagami-Agent-Proxy-macOS/releases";var notes:String="";var severity:String="unspecified";var recommendation:String="optional";var lastResult:String=""
}
struct QuotaWindow:Decodable,Identifiable {
    var id:String;var label:String;var usedPercent:Double?;var remainingAmount:Double?;var resetAt:Double?;var disabled:Bool?
}
struct SessionTelemetry:Decodable {
    var state:String?;var activityAt:Double?;var updatedAt:Double?;var source:String?;var model:String?;var contextUsed:Double?;var quotas:[QuotaWindow]?;var note:String?
    var isWorking:Bool? {switch state {case "working","tool_use","reviewing","initializing":return true;case "idle","authenticating","error","permission":return false;default:return nil}}
    var activityBadge:String {isWorking == true ? "В работе":(state == "idle" ? "Ожидает ввода":(isWorking == false ? "Не в работе":"Нет данных о работе"))}
    var activity:String {switch state {case "idle":return "Ожидает ввода";case "working":return "Готовит ответ";case "tool_use":return "Выполняет инструмент";case "reviewing":return "Проверяет результат";case "authenticating":return "Ожидает входа";case "initializing":return "Подготавливается";case "error":return "Клиент сообщил об ошибке";case "permission":return "Ожидает разрешения";default:return "Клиент пока не передал состояние"}}
}
struct TargetCheck:Decodable,Identifiable {
    var name:String;var host:String;var success:Bool;var latency_ms:Double?;var error:String?
    var id:String {host}
}
struct ConnectionReport:Decodable {var success:Bool;var targets:[TargetCheck];var errors:[String]}
struct ManagedSession:Decodable,Identifiable {
    var id:String;var name:String;var profile:String;var running:Bool;var browser:Bool;var stopping:Bool;var pid:Int;var pids:[Int];var bridge:String;var error:String
    var networkEngine:String?=nil;var app:String?=nil;var terminal:Bool?=nil;var canStop:Bool?=nil;var notice:String?=nil;var telemetry:SessionTelemetry?=nil
    var status:String {!error.isEmpty ? "Нет ответа":(stopping ? "Останавливается":(running ? (terminal == true ? "CLI в терминале":"Приложение запущено"):(browser ? "Открыт браузер входа":"Маршрут готов")))}
}
struct JournalEntry:Decodable,Identifiable {
    var id:String;var time:String;var action:String;var title:String;var success:Bool;var summary:String;var detail:String
    var displayTime:String {guard let date=ISO8601DateFormatter().date(from:time) else{return time};return date.formatted(date:.abbreviated,time:.shortened)}
}
struct AuthState:Decodable {
    var service:String?=nil;var profile:String?=nil
    var message:String="Сессия входа не запущена";var url:String="";var code:String="";var running:Bool=false
}
final class RPC: @unchecked Sendable {
    private let queue=DispatchQueue(label:"ru.dagami.bridge")
    private var process:Process?; private var input:FileHandle?;private var output:FileHandle?;private var buffer=Data()
    func call(_ action:String,_ args:[String:Any]=[:]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    if self.process == nil { try self.start() }
                    let data=try JSONSerialization.data(withJSONObject:["action":action,"args":args])
                    try self.input!.write(contentsOf:data+Data([10]))
                    while !self.buffer.contains(10) {
                        let chunk=self.output!.availableData
                        if chunk.isEmpty { throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:"Служба приложения завершилась. Перезапустите Dagami."]) }
                        self.buffer.append(chunk)
                    }
                    let end=self.buffer.firstIndex(of:10)!;let reply=self.buffer.prefix(upTo:end);self.buffer.removeSubrange(...end)
                    continuation.resume(returning:Data(reply))
                } catch { continuation.resume(throwing:error) }
            }
        }
    }
    private func start() throws {
        let resources=Bundle.main.resourceURL!
        let runtime=resources.appendingPathComponent("Python.framework/Versions/3.12")
        let task=Process();task.executableURL=runtime.appendingPathComponent("bin/python3.12")
        task.arguments=["-B","-I",resources.appendingPathComponent("Engine/native/macos/bridge.py").path]
        var env=ProcessInfo.processInfo.environment
        env["PYTHONHOME"]=runtime.path;env["PYTHONNOUSERSITE"]="1";env["PYTHONDONTWRITEBYTECODE"]="1"
        env["SSL_CERT_FILE"]=resources.appendingPathComponent("cacert.pem").path
        env["DAGAMI_NATIVE_APP"]=Bundle.main.executablePath!
        env["DAGAMI_BUNDLED_ENGINE"]="1"
        task.environment=env
        let read=Pipe(),write=Pipe();task.standardInput=write;task.standardOutput=read;task.standardError=FileHandle.nullDevice
        try task.run();process=task;input=write.fileHandleForWriting;output=read.fileHandleForReading
    }
    deinit { try? input?.close();process?.terminate() }
}
@MainActor final class Model:ObservableObject {
    @Published var page="Обзор";@Published var state=Snapshot();@Published var busy=false;@Published var message="Настройки сети под вашим контролем."
    @Published var profile="" {didSet{if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] != "1" {UserDefaults.standard.set(profile,forKey:"selectedProfile")}}}
    @Published var client="";@Published var ready=false;@Published var journal="Журнал пока пуст."
    @Published var auth=AuthState()
    @Published var quotaErrors:[String:String]=[:];private var quotaAttempts:[String:Date]=[:];@Published var quotaReports:[String:SessionTelemetry]=[:];@Published var sessions:[ManagedSession]=[];@Published var events:[JournalEntry]=[]
    @Published var showConnectionPanel=false;@Published var checkingConnection=false;@Published var connectionReport:ConnectionReport?;@Published var connectionProfile="";@Published var checkStarted=Date()
    private var clipboardWatching=false
    @Published var clipboardEnabled=true;@Published var authNetworkStatus=""
    @Published var installingUpdate=false;@Published var update=UpdateInfo();@Published var updateStatus="Проверка обновлений ещё не выполнялась."
    @Published var automaticUpdates=true {didSet{UserDefaults.standard.set(automaticUpdates,forKey:"automaticUpdateChecks")}}
    private var updateTimer:Timer?;private var updateAcknowledged=false;private var showingUpdateOffer=false;private var lastOfferedTag="";private var lastOfferedAt=Date.distantPast;private var lastUpdateAttempt=Date.distantPast;private var startupUpdateCheck=false
    private let clipboard=OAuthClipboard()
    private var clipboardTimer:Timer?
    let rpc=RPC()
    init() {
        UserDefaults.standard.register(defaults:["automaticUpdateChecks":true])
        automaticUpdates=UserDefaults.standard.bool(forKey:"automaticUpdateChecks")
        if let data=UserDefaults.standard.data(forKey:"cachedUpdate"),let cached=try? JSONDecoder().decode(UpdateInfo.self,from:data),cached.currentBuild==Int(Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") as? String ?? "0") {update=cached;updateStatus=cached.available ? "Доступна "+cached.tag:"Предыдущая проверка: новых версий не было."}
        if Bundle.main.object(forInfoDictionaryKey:"DagamiDesignTest") as? Bool == true {automaticUpdates=false;updateStatus="Тест дизайна. Обновления доступны в основной Dagami."}
        updateTimer=Timer.scheduledTimer(withTimeInterval:60,repeats:true){[weak self] _ in Task{@MainActor in self?.checkUpdatesIfDue()}}
        profile=UserDefaults.standard.string(forKey:"selectedProfile") ?? ""
        clipboardTimer=Timer.scheduledTimer(withTimeInterval:0.5,repeats:true){[weak self] _ in Task{@MainActor in self?.pollClipboard()}}
    }
    func checkUpdatesIfDue() {
        guard Bundle.main.object(forInfoDictionaryKey:"DagamiDesignTest") as? Bool != true,automaticUpdates,!busy,!auth.running,!showingUpdateOffer,ready,ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] != "1" else{return}
        let last=UserDefaults.standard.double(forKey:"lastUpdateCheck"),now=Date().timeIntervalSince1970
        guard Date().timeIntervalSince(lastUpdateAttempt)>900,(!startupUpdateCheck || now-last>21600 || now<last || update.currentBuild==0) else{return}
        startupUpdateCheck=true;lastUpdateAttempt=Date();run("updateCheck",["profile":profile],refresh:false)
    }
    func showUpdateOffer(manual:Bool) {
        guard update.available,!showingUpdateOffer else{return}
        if !manual && (!automaticUpdates || (lastOfferedTag==update.tag && Date().timeIntervalSince(lastOfferedAt)<86400)) {return}
        let deferredTag=UserDefaults.standard.string(forKey:"deferredUpdateTag") ?? ""
        if !manual && deferredTag==update.tag && Date().timeIntervalSince1970<UserDefaults.standard.double(forKey:"deferredUpdateUntil") {return}
        showingUpdateOffer=true;lastOfferedTag=update.tag;lastOfferedAt=Date()
        let alert=NSAlert();alert.messageText="Вышло обновление Dagami "+update.tag
        let severity=["normal":"Обычное обновление","important":"Важное обновление","critical":"Критическое обновление","unspecified":"Критичность не указана автором"]
        alert.alertStyle=update.severity=="critical" ? .warning:.informational
        alert.informativeText=(severity[update.severity] ?? "Обновление")+"\n"+(update.recommendation=="required" ? "Необходимо установить это обновление.":(update.recommendation=="recommended" ? "Рекомендуется установить сейчас.":"Можно установить позже."))+"\nПосле установки Dagami перезапустится. Профили и аккаунты сохранятся."
        let scroll=NSScrollView(frame:NSRect(x:0,y:0,width:440,height:200));scroll.hasVerticalScroller=true;scroll.borderType = .bezelBorder
        let text=NSTextView(frame:NSRect(x:0,y:0,width:420,height:200));text.isEditable=false;text.isSelectable=true;text.isVerticallyResizable=true;text.isHorizontallyResizable=false;text.maxSize=NSSize(width:440,height:CGFloat.greatestFiniteMagnitude);text.textContainer?.widthTracksTextView=true;text.font=NSFont.systemFont(ofSize:13);text.textContainerInset=NSSize(width:8,height:8);text.autoresizingMask=[.width];text.string=update.notes.isEmpty ? "Описание изменений не приложено. Подробности доступны на странице выпуска.":update.notes
        scroll.documentView=text;alert.accessoryView=scroll
        alert.addButton(withTitle:"Обновить");alert.addButton(withTitle:"Позже");alert.buttons[1].keyEquivalent="\u{1b}"
        NSApp.activate(ignoringOtherApps:true)
        let response=alert.runModal();showingUpdateOffer=false
        if response == .alertFirstButtonReturn {run("updateInstall",["tag":update.tag,"profile":profile],refresh:false)}
        else {UserDefaults.standard.set(update.tag,forKey:"deferredUpdateTag");UserDefaults.standard.set(Date().timeIntervalSince1970+86400,forKey:"deferredUpdateUntil");updateStatus="Установка отложена. Напомним через сутки; обновить вручную можно в настройках."}
    }
    private func pollClipboard() {
        let active=clipboardEnabled && auth.running && auth.profile==profile
        guard active else{if clipboardWatching {_ = clipboard.poll(enabled:false,service:auth.service ?? "");clipboardWatching=false};return}
        clipboardWatching=true
        guard !busy,let service=auth.service else{return}
        if let url=clipboard.poll(enabled:true,service:service) {auth.url=url;auth.message="Ссылка из буфера получена. Проверяется маршрут входа…";run("authClipboard",["url":url,"service":service,"profile":profile],refresh:false)}
        else if !clipboard.rejection.isEmpty {auth.message=clipboard.rejection;message=clipboard.rejection}
    }
    func refresh() {
        if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
            state=Snapshot();state.activated=true;state.systemDNS="Применён";state.profiles=[Profile(id:"ai",name:"ИИ — Smart DNS",dns:true,proxy:false,endpoints:["udp://89.22.224.205"],scope:"ai",domains:[])]
            state.apps=[ClientApp(id:"antigravity",name:"Google Antigravity",path:"fixture",installed:true,prepared:false),ClientApp(id:"codex",name:"Codex CLI",path:"fixture",installed:true,prepared:false),ClientApp(id:"claude",name:"Claude Code",path:"fixture",installed:true,prepared:false)]
            state.profiles.append(Profile(id:"proxy",name:"Рабочий прокси",dns:false,proxy:true,endpoints:[],scope:"ai",domains:[]))
            state.profiles.append(Profile(id:"backup",name:"Запасной DNS",dns:true,proxy:false,endpoints:["udp://2.56.175.196"],scope:"ai",domains:[]))
            sessions=[ManagedSession(id:"antigravity",name:"Antigravity IDE",profile:"ИИ — Smart DNS",running:true,browser:false,stopping:false,pid:1234,pids:[1235],bridge:"http://127.0.0.1:54084",error:"")]
            events=[JournalEntry(id:"fixture-error",time:"2026-11-02T01:00:00+05:00",action:"prepare",title:"Применение патча",success:false,summary:"Проверка подписи приложения не прошла. Откройте подробности.",detail:"Fixture: codesign exited with status 1\nstderr: invalid signature"),JournalEntry(id:"fixture-ok",time:"2026-11-02T00:59:00+05:00",action:"launch",title:"Запуск приложения",success:true,summary:"Команда запуска отправлена. Состояние приложения — в разделе «Сессии».",detail:"Fixture: application launched")]
            sessions[0].telemetry=try? JSONDecoder().decode(SessionTelemetry.self,from:JSONSerialization.data(withJSONObject:["state":"working","model":"Gemini","activityAt":Date().timeIntervalSince1970,"updatedAt":Date().timeIntervalSince1970,"source":"Официальные события клиента","note":"Демонстрационные данные; аккаунты не запрашиваются"]))
            quotaReports[sessions[0].id]=try? JSONDecoder().decode(SessionTelemetry.self,from:JSONSerialization.data(withJSONObject:["updatedAt":Date().timeIntervalSince1970,"source":"Локальный сервер Antigravity · внутренний интерфейс","quotas":[["id":"gemini-five-hour","label":"Gemini · 5h","usedPercent":28,"resetAt":Date().addingTimeInterval(5460).timeIntervalSince1970],["id":"gemini-weekly","label":"Gemini · weekly","usedPercent":82,"resetAt":Date().addingTimeInterval(187200).timeIntervalSince1970]],"note":"Лимиты аккаунта, общие для сессий. Демонстрационные значения."]))
            state.services=[NetworkService(id:"Ethernet",name:"Ethernet"),NetworkService(id:"Wi-Fi",name:"Wi-Fi")];profile="ai";ready=true
            if let preview=ProcessInfo.processInfo.environment["DAGAMI_UI_CHECK_PREVIEW"] {
                connectionProfile="ИИ — Smart DNS";checkStarted=Date();checkingConnection=preview=="running";showConnectionPanel=true
                if preview != "running" {connectionReport=ConnectionReport(success:preview=="success",targets:[TargetCheck(name:"Google AI",host:"generativelanguage.googleapis.com",success:true,latency_ms:180,error:nil),TargetCheck(name:"OpenAI API",host:"api.openai.com",success:preview=="success",latency_ms:245,error:preview=="success" ? nil:"HTTP 503 Service Unavailable"),TargetCheck(name:"Anthropic API",host:"api.anthropic.com",success:true,latency_ms:196,error:nil),TargetCheck(name:"GitHub",host:"github.com",success:true,latency_ms:95,error:nil)],errors:[])}
            }
            return
        }
        run("snapshot",refresh:false)
    }
    func run(_ action:String,_ args:[String:Any]=[:],refresh:Bool=true) {
        guard !busy,!showingUpdateOffer else{return}
        if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
            if ["sessions","journalEntries"].contains(action) {return}
            message="Демонстрация дизайна · сетевые действия отключены";return
        }
        if action.hasPrefix("update") && Bundle.main.object(forInfoDictionaryKey:"DagamiDesignTest") as? Bool == true {updateStatus="Тест дизайна. Обновления доступны в основной Dagami.";return}
        busy=true
        if action=="sessionQuota",let id=args["session"] as? String {quotaAttempts[id]=Date();quotaErrors.removeValue(forKey:id)}
        if action=="checkConnection" {NSApp.activate(ignoringOtherApps:true);NSApp.windows.first(where:{$0.frame.width>=700})?.makeKeyAndOrderFront(nil);showConnectionPanel=true;checkingConnection=true;connectionReport=nil;connectionProfile=args["profile"] as? String ?? profile;checkStarted=Date();message="Проверяем TLS-подключение к ИИ-сервисам…"}
        if action=="updateInstall" {installingUpdate=true;message="Скачиваем обновление и проверяем SHA-256 и подпись…";updateStatus=message}
        Task {
            do {
                let targetApp = (args["app"] as? String) ?? (action=="prepareAuth" ? "antigravity" : nil)
                if ["launch","prepare","restore","unpatch","prepareAuth","repairIDE"].contains(action),let app=targetApp {
                    let inspected=try await rpc.call("appInspect",["app":app])
                    let reply=try JSONSerialization.jsonObject(with:inspected) as! [String:Any]
                    if reply["ok"] as? Bool != true {throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:reply["error"] as? String ?? "Не удалось проверить процессы"])}
                    let result=reply["result"] as? [String:Any] ?? [:]
                    let processes=result["processes"] as? [[String:Any]] ?? []
                    if result["cli"] as? Bool != true && !processes.isEmpty {
                        let alert=NSAlert();alert.messageText="У вас открыты процессы ИИ-приложения"
                        let names=processes.prefix(12).map{($0["name"] as? String ?? "Процесс")+" (PID "+String($0["pid"] as? Int ?? 0)+")"}.joined(separator:"\n")
                        alert.informativeText="Сохраните несохранённые данные перед закрытием.\n\n"+names+"\n\nПродолжить после закрытия процессов?"
                        alert.addButton(withTitle:"Закрыть процессы");alert.addButton(withTitle:"Отменить")
                        if alert.runModal() != .alertFirstButtonReturn {busy=false;return}
                        let closed=try await rpc.call("appClose",["app":app]);let response=try JSONSerialization.jsonObject(with:closed) as! [String:Any]
                        if response["ok"] as? Bool != true {throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:response["error"] as? String ?? "Процессы не закрыты"])}
                    }
                }
                let bytes=try await rpc.call(action,args)
                let json=try JSONSerialization.jsonObject(with:bytes) as! [String:Any]
                if json["ok"] as? Bool != true { throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:json["error"] as? String ?? "Операция не завершена"]) }
                if action=="snapshot" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    state=try JSONDecoder().decode(Snapshot.self,from:data);ready=true
                    if !updateAcknowledged {let _=try? await rpc.call("updateAck");updateAcknowledged=true}
                    if !state.profiles.contains(where:{$0.id==profile}) { profile=state.profiles.first?.id ?? "" }
                    if !state.apps.contains(where:{$0.id==client}) { client=state.apps.first(where:{$0.installed})?.id ?? state.apps.first?.id ?? "" }
                } else if action=="sessions" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    sessions=try JSONDecoder().decode([ManagedSession].self,from:data)
                } else if action=="sessionQuota" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    if let id=args["session"] as? String {quotaReports[id]=try JSONDecoder().decode(SessionTelemetry.self,from:data)}
                    message="Данные лимитов обновлены."
                } else if action=="journalEntries" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    events=try JSONDecoder().decode([JournalEntry].self,from:data)
                } else if action=="checkConnection" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    let report=try JSONDecoder().decode(ConnectionReport.self,from:data)
                    connectionReport=report;checkingConnection=false
                    message=report.success ? "Подключение проверено: TLS работает.":"Есть ошибки подключения. Подробности — в проверке связи и журнале."
                } else if action=="updateCheck" {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    update=try JSONDecoder().decode(UpdateInfo.self,from:data);UserDefaults.standard.set(data,forKey:"cachedUpdate");UserDefaults.standard.set(Date().timeIntervalSince1970,forKey:"lastUpdateCheck")
                    updateStatus=update.available ? "Вышла версия "+update.tag:"Установлена последняя доступная версия."
                    if !update.lastResult.isEmpty {updateStatus+="\n"+update.lastResult}
                } else if action=="probeAuth" {
                    authNetworkStatus=json["result"] as? String ?? "Проверка завершена"
                } else if action=="authFind" {
                    let value=json["result"] as? String ?? ""
                    if !value.isEmpty {auth.url=value;auth.message="Свежая ссылка найдена"} else {auth.message="Свежая ссылка не найдена. Начните вход в приложении."}
                } else if action.hasPrefix("auth") {
                    let data=try JSONSerialization.data(withJSONObject:json["result"]!)
                    auth=try JSONDecoder().decode(AuthState.self,from:data)
                    if action=="authStart" || action=="authStop" {clipboard.reset()}
                } else if action=="journal" {journal=json["result"] as? String ?? "Журнал пока пуст."
                } else {
                    message=(json["result"] as? String) ?? "Готово"
                }
                busy=false
                if action=="updateInstall" {NSApp.terminate(nil);return}
                if action=="updateCheck" {showUpdateOffer(manual:args["manual"] as? Bool ?? false)}
                if action=="snapshot" {checkUpdatesIfDue()}
                if action=="sessions" {refreshQuotaIfDue()}
                if action=="stop" {self.run("sessions",refresh:false);return}
                if action=="profileDelete" && args["name"] as? String == connectionProfile {connectionReport=nil}
                if refresh && action != "checkConnection" { self.refresh() }
            } catch { if action=="sessionQuota",let id=args["session"] as? String {quotaErrors[id]=error.localizedDescription};if action=="checkConnection" {connectionReport=ConnectionReport(success:false,targets:[],errors:[error.localizedDescription])};checkingConnection=false;message=error.localizedDescription;if action.hasPrefix("update") {installingUpdate=false;updateStatus=error.localizedDescription};if action=="authClipboard" {clipboard.reset()};if action.hasPrefix("auth") {auth.message=error.localizedDescription};if action=="probeAuth" {authNetworkStatus=error.localizedDescription};busy=false;ready=true }
        }
    }
    func refreshQuotaIfDue() {
        guard page=="Сессии",state.monitoring ?? true,!busy,ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] != "1" else{return}
        let live=Set(sessions.map{$0.id});quotaReports=quotaReports.filter{live.contains($0.key)};quotaErrors=quotaErrors.filter{live.contains($0.key)}
        if let session=sessions.first(where:{["codex","codex-gui","antigravity","antigravity-ide"].contains($0.app ?? $0.id) && Date().timeIntervalSince(quotaAttempts[$0.id] ?? .distantPast)>120}) {run("sessionQuota",["session":session.id],refresh:false)}
    }
    func profileRequest(_ action:String,_ args:[String:Any]) async throws->Data {
        guard !busy else{throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:"Дождитесь завершения текущей операции."])}
        if ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
            guard action=="profileDetails",let name=args["name"] as? String,let profile=state.profiles.first(where:{$0.id==name}) else{throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:"Демонстрация дизайна: изменения отключены."])}
            return try JSONSerialization.data(withJSONObject:["name":profile.name,"url":profile.proxy ? "https://fixture-user:fixture%40password@proxy.example:8443":"direct://","proxy":profile.proxy,"dns":profile.dns,"endpoints":profile.endpoints,"scope":profile.scope,"domains":profile.domains])
        }
        busy=true;defer{busy=false}
        let bytes=try await rpc.call(action,args)
        let json=try JSONSerialization.jsonObject(with:bytes) as! [String:Any]
        guard json["ok"] as? Bool == true else{throw NSError(domain:"Dagami",code:1,userInfo:[NSLocalizedDescriptionKey:json["error"] as? String ?? "Не удалось выполнить действие с профилем."])}
        return try JSONSerialization.data(withJSONObject:json["result"]!,options:.fragmentsAllowed)
    }
    var chosen:Profile? {state.profiles.first{$0.id==profile}}
}
final class Delegate:NSObject,NSApplicationDelegate,NSWindowDelegate {
    func applicationDidFinishLaunching(_ notification:Notification) {
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
            NSApp.windows.first?.delegate=self
            if let path=ProcessInfo.processInfo.environment["DAGAMI_UI_SCREENSHOT"] {
                DispatchQueue.main.asyncAfter(deadline:.now()+2) {
                    if let window=NSApp.windows.first(where:{$0.frame.width>700}),let view=(ProcessInfo.processInfo.environment["DAGAMI_UI_GALLERY"]=="1" ? window.attachedSheet?.contentView:window.contentView),
                       let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds) {
                        view.cacheDisplay(in:view.bounds,to:rep)
                        try? rep.representation(using:.png,properties:[:])?.write(to:URL(fileURLWithPath:path))
                    }
                }
            }
            if let path=ProcessInfo.processInfo.environment["DAGAMI_UI_PANEL_SCREENSHOT"],ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
                for (index,delay) in [2.0,2.6].enumerated() {
                    DispatchQueue.main.asyncAfter(deadline:.now()+delay) {
                        if let view=NSApp.windows.first(where:{$0.frame.width>400 && $0.frame.width<600})?.contentView,let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds) {
                            view.cacheDisplay(in:view.bounds,to:rep)
                            let target=index==0 ? path:path+".next.png"
                            try? rep.representation(using:.png,properties:[:])?.write(to:URL(fileURLWithPath:target))
                        }
                    }
                }
            }
            if let path=ProcessInfo.processInfo.environment["DAGAMI_UI_TRAY_SCREENSHOT"],ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1" {
                DispatchQueue.main.asyncAfter(deadline:.now()+2) {
                    let fixture=Model();fixture.refresh()
                    let host=NSHostingView(rootView:TrayView().environmentObject(fixture))
                    host.setFrameSize(host.fittingSize);host.layoutSubtreeIfNeeded()
                    if let rep=host.bitmapImageRepForCachingDisplay(in:host.bounds) {
                        host.cacheDisplay(in:host.bounds,to:rep)
                        try? rep.representation(using:.png,properties:[:])?.write(to:URL(fileURLWithPath:path))
                    }
                }
            }
            if CommandLine.arguments.contains("--autostart") { NSApp.hide(nil) }
        }
    }
    func windowShouldClose(_ sender:NSWindow)->Bool { sender.orderOut(nil);return false }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool)->Bool { NSApp.windows.first?.makeKeyAndOrderFront(nil);return true }
}
@main struct DagamiApp:App {
    @NSApplicationDelegateAdaptor(Delegate.self) var delegate
    @StateObject var model=Model()
    var body:some Scene {
        WindowGroup(designTest ? "Dagami · Лимиты":"Dagami") {
            RootView().environmentObject(model).frame(minWidth:820,minHeight:600)
                .tint(.blue).toggleStyle(.switch).preferredColorScheme(ProcessInfo.processInfo.environment["DAGAMI_UI_THEME"]=="light" ? .light:(ProcessInfo.processInfo.environment["DAGAMI_UI_THEME"]=="dark" ? .dark:nil)).onAppear{if !model.ready {model.refresh()};if let page=ProcessInfo.processInfo.environment["DAGAMI_UI_PAGE"] {model.page=page}}
        }.windowStyle(.hiddenTitleBar).defaultSize(width:860,height:650)
        MenuBarExtra(designTest ? "Dagami · Лимиты":"Dagami",systemImage:"circle.hexagongrid.fill") {
            TrayView().environmentObject(model)
        }.menuBarExtraStyle(.window)
    }
}
final class SmoothIconView:NSView {
    private static var images:[String:NSImage]=[:]
    private var asset="";private var sourceImage:NSImage?
    override var isOpaque:Bool {false}
    override var isFlipped:Bool {true}
    override func hitTest(_ point:NSPoint)->NSView? {nil}
    override var intrinsicContentSize:NSSize {NSSize(width:NSView.noIntrinsicMetric,height:NSView.noIntrinsicMetric)}
    func configure(asset:String,image:NSImage?) {
        guard self.asset != asset || sourceImage !== image else{return}
        self.asset=asset;sourceImage=image;needsDisplay=true
    }
    override func viewDidChangeBackingProperties(){super.viewDidChangeBackingProperties();needsDisplay=true}
    override func setFrameSize(_ newSize:NSSize){super.setFrameSize(newSize);needsDisplay=true}
    private func image(pixels:Int)->NSImage? {
        if let sourceImage=sourceImage{return sourceImage}
        let key=asset+"/"+String(pixels)
        if let cached=Self.images[key]{return cached}
        guard let root=Bundle.main.resourceURL?.appendingPathComponent("Engine/native/macos/BrandIcons") else{return nil}
        let exact=root.appendingPathComponent("raster/"+asset+"/"+String(pixels)+".png")
        guard let image=NSImage(contentsOf:exact) ?? NSImage(contentsOf:root.appendingPathComponent(asset+".png")) else{return nil}
        image.isTemplate=false;Self.images[key]=image;return image
    }
    override func draw(_ dirtyRect:NSRect) {
        let rect=backingAlignedRect(bounds,options:.alignAllEdgesNearest)
        let pixels=max(1,Int(convertToBacking(rect).width.rounded()))
        guard let image=image(pixels:pixels),let context=NSGraphicsContext.current else{return}
        NSGraphicsContext.saveGraphicsState()
        context.imageInterpolation = .high;context.shouldAntialias=true
        context.cgContext.setAllowsAntialiasing(true)
        image.draw(in:rect,from:.zero,operation:.sourceOver,fraction:1,respectFlipped:true,hints:nil)
        NSGraphicsContext.restoreGraphicsState()
    }
}
struct SmoothIcon:NSViewRepresentable {
    var asset="";var image:NSImage?=nil
    func makeNSView(context:Context)->SmoothIconView {
        let view=SmoothIconView();view.wantsLayer=true;view.layerContentsRedrawPolicy = .onSetNeedsDisplay
        view.setAccessibilityElement(false);return view
    }
    func updateNSView(_ view:SmoothIconView,context:Context){view.configure(asset:asset,image:image)}
}
struct BrandImage:View {
    @Environment(\.colorScheme) var scheme
    var name:String
    private static let names:Set<String>={
        guard let root=Bundle.main.resourceURL?.appendingPathComponent("Engine/native/macos/BrandIcons"),let files=try? FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:nil) else{return []}
        return Set(files.filter{$0.pathExtension=="png"}.map{$0.deletingPathExtension().lastPathComponent})
    }()
    static func contains(_ name:String)->Bool {names.contains(name+"-light")}
    var body:some View {
        if Self.contains(name){SmoothIcon(asset:name+(scheme == .dark ? "-dark":"-light"))}
        else {Image(systemName:"app.fill").resizable().aspectRatio(contentMode:.fit).foregroundStyle(.secondary)}
    }
}
struct AppGlyph:View {
    @EnvironmentObject var model:Model
    private static var nativeImages:[String:NSImage]=[:]
    var id:String;var small=false
    var brand:String {
        let names=["antigravity","opencode","vscodium","vscode","cursor","windsurf","github","git","claude","gemini","deepseek","qwen","grok","perplexity","mistral","openrouter","copilot","ollama"]
        if let name=names.first(where:{id.contains($0)}) {return name}
        if id=="agy" {return "antigravity"}
        if id.contains("codex") || id.contains("chatgpt") || id.contains("openai") {return "openai"}
        return id
    }
    var nativeImage:NSImage? {
        guard let path=model.state.apps.first(where:{$0.id==id})?.path,!path.isEmpty else{return nil}
        let target:String
        if let range=path.range(of:".app/"){target=String(path[..<range.upperBound].dropLast())}else{target=path}
        if let image=Self.nativeImages[target]{return image}
        let image=NSWorkspace.shared.icon(forFile:target);Self.nativeImages[target]=image;return image
    }
    @ViewBuilder var artwork:some View {
        if BrandImage.contains(brand){BrandImage(name:brand)}
        else if let image=nativeImage {SmoothIcon(image:image)}
        else {Image(systemName:"app.fill").resizable().aspectRatio(contentMode:.fit).foregroundStyle(.secondary)}
    }
    var body:some View {
        artwork.frame(width:small ? 18:26,height:small ? 18:26)
            .frame(width:small ? 30:42,height:small ? 30:42)
            .background(Color.primary.opacity(0.045),in:RoundedRectangle(cornerRadius:small ? 9:13,style:.continuous)).accessibilityHidden(true)
    }
}
struct SoftButton:ButtonStyle {
    func makeBody(configuration:Configuration)->some View {
        configuration.label.padding(.horizontal,12).padding(.vertical,8)
            .background(Color.primary.opacity(configuration.isPressed ? 0.09:0.045),in:RoundedRectangle(cornerRadius:10,style:.continuous))

    }
}
struct Card<Content:View>:View {
    @ViewBuilder var content:Content
    var body:some View {
        VStack(alignment:.leading,spacing:13){content}.padding(17)
            .frame(maxWidth:.infinity,alignment:.leading)
            .background(Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:18,style:.continuous))
            .overlay(RoundedRectangle(cornerRadius:18,style:.continuous).strokeBorder(.primary.opacity(0.045)))

    }
}
struct TrayView:View {
    @EnvironmentObject var model:Model
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    func open(_ page:String) {
        model.page=page;NSApp.activate(ignoringOtherApps:true)
        NSApp.windows.first(where:{$0.frame.width>=700})?.makeKeyAndOrderFront(nil)
    }
    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            HStack(spacing:9) {
                Image(systemName:"circle.hexagongrid.fill").font(.title2).foregroundStyle(.blue)
                VStack(alignment:.leading,spacing:2){Text("Dagami").font(.headline);Text("Быстрый доступ").font(.caption2).foregroundStyle(.secondary)}
                Spacer()
                if model.busy {ProgressView().controlSize(.mini)}
                Button{open("Настройки")}label:{Image(systemName:"gearshape").font(.system(size:14))}.buttonStyle(.plain).help("Настройки")
            }
            Divider()
            if !model.ready {ProgressView("Загрузка…").controlSize(.small)}
            else if !model.state.activated {Button("Активировать Dagami"){open("Обзор")}.buttonStyle(.borderedProminent)}
            else {
                VStack(alignment:.leading,spacing:5) {
                    Text("ПРОФИЛЬ").font(.system(size:9,weight:.semibold)).tracking(1).foregroundStyle(.secondary)
                    if model.state.profiles.isEmpty {Button("Добавить профиль"){open("Профили")}}
                    else {Picker("Профиль",selection:$model.profile){ForEach(model.state.profiles){Text($0.name).tag($0.id)}}.labelsHidden().frame(maxWidth:.infinity).disabled(model.busy)
                        Text(model.chosen?.subtitle ?? "Выберите профиль").font(.caption2).foregroundStyle(.secondary)}
                }
                Button{model.run("checkConnection",["profile":model.profile])}label:{HStack(spacing:7){if model.checkingConnection {ProgressView().controlSize(.mini)}else{Image(systemName:"waveform.path.ecg")};Text(model.checkingConnection ? "Проверяем…":"Проверить связь")}.frame(maxWidth:.infinity)}.buttonStyle(SoftButton()).disabled(model.busy || model.profile.isEmpty)
                if !model.message.isEmpty {Text(model.message).font(.caption2).foregroundStyle(.secondary).lineLimit(2).help(model.message)}
                let apps=Array(model.state.apps.filter{$0.installed}.prefix(3))
                if !apps.isEmpty {
                    Divider()
                    ForEach(apps){app in
                        Button{model.client=app.id;model.run("launch",["app":app.id,"profile":model.profile])}label:{
                            HStack(spacing:9){AppGlyph(id:app.id,small:true);Text(app.name).font(.system(size:12,weight:.medium)).lineLimit(1);Spacer();Image(systemName:"play.fill").font(.system(size:9)).foregroundStyle(.secondary)}.contentShape(Rectangle())
                        }.buttonStyle(.plain).disabled(model.busy || model.profile.isEmpty || app.launchError != nil)
                    }
                }
            }
            Divider()
            HStack {
                Button("Открыть"){open("Обзор")}.buttonStyle(.plain).font(.system(size:12,weight:.semibold)).foregroundStyle(.blue)
                Spacer()
                Button{open("Сессии")}label:{Image(systemName:"rectangle.stack")}.buttonStyle(.plain).help("Сессии")
                Button{open("Журнал")}label:{Image(systemName:"text.alignleft")}.buttonStyle(.plain).help("Журнал")
                Button{NSApp.terminate(nil)}label:{Image(systemName:"power")}.buttonStyle(.plain).help("Выйти из Dagami")
            }
        }.padding(16).frame(width:276)

    }
}
struct RootView:View {
    @EnvironmentObject var model:Model
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var page:String {get{model.page} nonmutating set{model.page=newValue}}
    @State private var mainPage="Обзор";@State private var networkPage="Авторизация"
    let sections=[("Главная","house.fill"),("Подключение","network"),("Журнал","text.alignleft"),("Настройки","gearshape.fill")]
    var section:String {if ["Обзор","Профили","Приложения","Сессии"].contains(page){return "Главная"};if ["Авторизация","DNS в системе"].contains(page){return "Подключение"};return page}
    var tabs:[(String,String)] {section=="Главная" ? [("Обзор","square.grid.2x2"),("Профили","slider.horizontal.3"),("Приложения","app"),("Сессии","rectangle.stack")]:[("Авторизация","person.crop.circle"),("DNS в системе","globe")]}
    func chooseSection(_ name:String){page=name=="Главная" ? mainPage:(name=="Подключение" ? networkPage:name)}
    var body:some View {
        Group {
            if !model.ready { ProgressView("Запускаем Dagami…").frame(maxWidth:.infinity,maxHeight:.infinity) }
            else if !model.state.activated { ActivationView() }
            else {
                HStack(spacing:0) {
                    VStack(alignment:.leading,spacing:18) {
                        HStack(spacing:9){Image(systemName:"circle.hexagongrid.fill").font(.system(size:26)).foregroundStyle(.blue);VStack(alignment:.leading,spacing:1){Text("Dagami").font(.system(size:18,weight:.bold,design:.rounded));Text(designTest ? "Лимиты · тест":"Agent Proxy").font(.system(size:10)).foregroundStyle(.secondary)}}.padding(.top,30).padding(.horizontal,16)
                        VStack(spacing:5){ForEach(Array(sections.enumerated()),id:\.element.0){index,item in
                            Button{chooseSection(item.0)}label:{HStack(spacing:9){
                                Image(systemName:item.1).font(.system(size:12,weight:.semibold)).foregroundStyle(.white).frame(width:25,height:25).background(navColor(index),in:RoundedRectangle(cornerRadius:7,style:.continuous))
                                Text(item.0=="Подключение" ? "Сеть и вход":item.0).font(.system(size:12,weight:section==item.0 ? .semibold:.regular)).lineLimit(1);Spacer(minLength:0)
                            }.padding(.horizontal,9).padding(.vertical,7).background(section==item.0 ? Color.blue.opacity(0.10):.clear,in:RoundedRectangle(cornerRadius:11,style:.continuous)).contentShape(Rectangle())}.buttonStyle(.plain)
                        }}.padding(.horizontal,8)
                        Spacer()
                        VStack(alignment:.leading,spacing:4){Text("Сделано для Mac").font(.system(size:11,weight:.medium));Text(designTest ? "Universal · mac.28 test":"Universal · mac.28 beta").font(.system(size:10)).foregroundStyle(.secondary)}.padding(17)
                    }.frame(width:158).background(Color(nsColor:.controlBackgroundColor))
                    Divider().opacity(0.5)
                    VStack(spacing:0) {
                        HStack(alignment:.center) {
                            VStack(alignment:.leading,spacing:4){Text(section).font(.system(size:25,weight:.bold,design:.rounded));Text(subtitle).font(.system(size:12)).foregroundStyle(.secondary)}
                            Spacer()
                            if model.busy {ProgressView().controlSize(.small)}
                            Button{model.refresh()}label:{Image(systemName:"arrow.clockwise").font(.system(size:13,weight:.medium))}.buttonStyle(SoftButton()).help("Обновить данные")
                        }.padding(.horizontal,22).padding(.top,27).padding(.bottom,18)
                        if section=="Главная" || section=="Подключение" {
                            PageTabs(items:tabs).padding(.horizontal,22).padding(.bottom,16)
                        }
                        if model.checkingConnection && !model.showConnectionPanel {
                            Button{model.showConnectionPanel=true}label:{HStack(spacing:8){ProgressView().controlSize(.mini);Text("Проверяем связь…");Spacer();Text("Показать").foregroundStyle(.blue)}.font(.system(size:11)).padding(11).background(Color.blue.opacity(0.06),in:RoundedRectangle(cornerRadius:10))}.buttonStyle(.plain).padding(.horizontal,22).padding(.bottom,10)
                        }
                        ScrollView {
                            VStack(spacing:15){pageContent}
                                .padding(.horizontal,22).padding(.bottom,20)
                        }
                        HStack(spacing:8){
                            Image(systemName:model.busy ? "arrow.triangle.2.circlepath":"info.circle").foregroundStyle(.blue)
                            Text(model.message).font(.system(size:10)).lineLimit(2).textSelection(.enabled).help(model.message)
                            Spacer(minLength:0)
                            Button{page="Журнал"}label:{Image(systemName:"text.alignleft")}.buttonStyle(.plain).help("Открыть журнал")
                        }.padding(.horizontal,20).padding(.vertical,11).background(Color(nsColor:.controlBackgroundColor))
                    }.background(Color(nsColor:.windowBackgroundColor))
                }

            }
        }
        .onChange(of:page){value in if ["Обзор","Профили","Приложения","Сессии"].contains(value){mainPage=value};if ["Авторизация","DNS в системе"].contains(value){networkPage=value}}
        .sheet(isPresented:$model.showConnectionPanel){ConnectionPanel().environmentObject(model)}
        .disabled(model.installingUpdate)
        .overlay {if model.installingUpdate {VStack(spacing:14){ProgressView();Text("Скачиваем и проверяем обновление…").font(.headline);Text("После установки Dagami перезапустится.").foregroundStyle(.secondary)}.padding(30).background(.regularMaterial,in:RoundedRectangle(cornerRadius:18))}}
    }
    var subtitle:String {switch page {case "Обзор":return "Профиль, приложения и быстрые действия.";case "Профили":return "Нажмите на профиль, чтобы выбрать его.";case "Сессии":return "Приложения и их маршруты через Dagami.";case "Журнал":return "Запуски, проверки и ошибки.";case "Приложения":return "Запускайте нужные инструменты одним нажатием.";case "DNS в системе":return "Настройки сети macOS с резервной копией и откатом.";default:return "Настройте Dagami под себя."}}
    @ViewBuilder var pageContent:some View {
        switch page {
        case "Профили":ProfilesView()
        case "Приложения":AppsView()
        case "DNS в системе":SystemDNSView()
        case "Настройки":settings
        case "Журнал":JournalView()
        case "Сессии":SessionsView()
        case "Авторизация":AuthView()
        default:overview
        }
    }
    func navColor(_ index:Int)->Color {[.blue,.teal,.orange,.gray][index]}
    var overview:some View {
        VStack(spacing:15) {
            VStack(alignment:.leading,spacing:18) {
                HStack(spacing:12){
                    Image(systemName:model.chosen?.dns == true ? "globe.europe.africa.fill":"shield.lefthalf.filled").font(.system(size:25,weight:.medium)).foregroundStyle(.white).frame(width:54,height:54).background(.white.opacity(0.16),in:RoundedRectangle(cornerRadius:16,style:.continuous))
                    VStack(alignment:.leading,spacing:5){Text("ВАШЕ ПОДКЛЮЧЕНИЕ").font(.system(size:9,weight:.semibold)).tracking(1.2).foregroundStyle(.white.opacity(0.7));Text(model.chosen?.name ?? "Добавьте профиль").font(.system(size:20,weight:.bold,design:.rounded)).lineLimit(2);Text(model.chosen?.subtitle ?? "Smart DNS или ваш прокси").font(.system(size:12)).foregroundStyle(.white.opacity(0.8))}
                    Spacer(minLength:0)
                }
                HStack(spacing:9){
                    Button{model.run("checkConnection",["profile":model.profile])}label:{HStack(spacing:7){if model.checkingConnection {ProgressView().controlSize(.mini)}else{Image(systemName:"waveform.path.ecg")};Text(model.checkingConnection ? "Проверяем…":"Проверить связь")}.font(.system(size:12,weight:.semibold)).padding(.horizontal,13).padding(.vertical,9).foregroundStyle(.blue).background(.white,in:RoundedRectangle(cornerRadius:10,style:.continuous))}.buttonStyle(.plain).disabled(model.profile.isEmpty || model.busy)
                    Button{page="Профили"}label:{Label("Сменить",systemImage:"arrow.left.arrow.right").font(.system(size:12,weight:.medium)).padding(.horizontal,12).padding(.vertical,9).background(.white.opacity(0.14),in:RoundedRectangle(cornerRadius:10,style:.continuous))}.buttonStyle(.plain)
                }
            }.padding(20).frame(maxWidth:.infinity,alignment:.leading).foregroundStyle(.white)
                .background(LinearGradient(colors:[Color(red:0.12,green:0.43,blue:0.96),Color(red:0.25,green:0.31,blue:0.84)],startPoint:.topLeading,endPoint:.bottomTrailing),in:RoundedRectangle(cornerRadius:22,style:.continuous))
            HStack(spacing:12){
                Button{page="DNS в системе"}label:{Card{Label("DNS в системе",systemImage:"globe").font(.system(size:12,weight:.semibold)).foregroundStyle(.blue);Text(model.state.systemDNS).font(.system(size:12)).lineLimit(2).foregroundStyle(.primary);HStack{Text("Настроить");Spacer();Image(systemName:"chevron.right")}.font(.system(size:10)).foregroundStyle(.secondary)}}.buttonStyle(.plain)
                Button{page="Авторизация"}label:{Card{Label("Вход в аккаунт",systemImage:"person.crop.circle").font(.system(size:12,weight:.semibold)).foregroundStyle(.teal);Text("Через ваш профиль").font(.system(size:12)).foregroundStyle(.primary);HStack{Text("Открыть");Spacer();Image(systemName:"chevron.right")}.font(.system(size:10)).foregroundStyle(.secondary)}}.buttonStyle(.plain)
            }.fixedSize(horizontal:false,vertical:true)
            if model.checkingConnection || model.connectionReport != nil {ConnectionCheckView()}
            AppsView(compact:true)
        }
    }
    var settings:some View {
        VStack(spacing:20){Card{Label("Статистика сессий",systemImage:"chart.bar.xaxis").font(.headline);Toggle("Показывать активность и лимиты клиентов",isOn:Binding(get:{model.state.monitoring ?? true},set:{model.run("sessionMonitoring",["enabled":$0])})).disabled(model.busy);Text("Для новых запусков CLI через Dagami используются официальные события и status line. Сохраняются только состояние, модель и числовые счётчики; тексты запросов и ответов не сохраняются.").font(.caption).foregroundStyle(.secondary);Button((model.state.desktopMonitoring ?? false) ? "Отключить активность Antigravity App / IDE":"Подключить активность Antigravity App / IDE"){model.run("desktopMonitoring",["enabled":!(model.state.desktopMonitoring ?? false)])}.disabled(model.busy);Text("Антигравити использует официальное правило hooks. После подключения перезапустите приложение через Dagami. Лимиты App / IDE читаются при открытой вкладке сессий или по кнопке через внутренний локальный интерфейс.").font(.caption).foregroundStyle(.secondary)};Card{Label("Обновления Dagami",systemImage:"arrow.triangle.2.circlepath").font(.headline);Toggle("Проверять новые версии автоматически",isOn:$model.automaticUpdates).disabled(Bundle.main.object(forInfoDictionaryKey:"DagamiDesignTest") as? Bool == true);Text(model.updateStatus).font(.callout).foregroundStyle(.secondary).textSelection(.enabled);Text("Бета-линия macOS. Проверка при запуске и раз в 6 часов. Плашка показывает изменения и критичность; «Позже» откладывает напоминание на сутки.").font(.caption).foregroundStyle(.secondary);HStack{Button("Проверить обновления"){model.run("updateCheck",["profile":model.profile,"manual":true],refresh:false)}.disabled(model.busy);if model.update.available {Button("Обновить сейчас"){model.showUpdateOffer(manual:true)}.disabled(model.busy)};Link("Все выпуски",destination:URL(string:"https://github.com/ImRealDerli/Dagami-Agent-Proxy-macOS/releases")!)}};LicenseSettingsView();Card{Label("При входе в систему",systemImage:"power").font(.headline);Toggle("Запускать Dagami вместе с macOS",isOn:Binding(get:{model.state.startup},set:{model.run("startup",["enabled":$0])})).disabled(model.busy);Text("Настройка использует пользовательский LaunchAgent.").font(.caption).foregroundStyle(.secondary)}
            Card{Text("Dagami Agent Proxy").font(.title2.bold());Text("Сетевой транспорт: "+(model.state.networkEngine ?? "Нет данных")).font(.caption).foregroundStyle(.secondary);Text(designTest ? "Тест нового дизайна · Universal · mac.28":"0.4.1 mac.28 beta · Universal").foregroundStyle(.secondary);HStack{Link("Поддержка",destination:URL(string:"https://t.me/dagamvi")!);Link(destination:URL(string:"https://github.com/ImRealDerli/Dagami-Agent-Proxy-macOS/issues")!){HStack(spacing:6){BrandImage(name:"github").frame(width:15,height:15);Text("Сообщить об ошибке")}}};HStack{Link(destination:URL(string:"https://github.com/j46871417-ui/Dagami-Agent-Proxy")!){HStack(spacing:6){BrandImage(name:"github").frame(width:15,height:15);Text("Официальный репозиторий")}};Link(destination:URL(string:"https://github.com/ImRealDerli")!){HStack(spacing:6){BrandImage(name:"github").frame(width:15,height:15);Text("Портер на Mac — ImRealDerli")}}}.buttonStyle(.bordered)}
        }
    }
}
struct ActivationView:View {
    @EnvironmentObject var model:Model;@State var key=""
    var body:some View {VStack(spacing:22){Image(systemName:"network").font(.system(size:60)).foregroundStyle(.blue);Text("Добро пожаловать в Dagami").font(.system(size:30,weight:.bold,design:.rounded));Text("Ваши приложения. Ваш маршрут.").foregroundStyle(.secondary);SecureField("Ключ доступа DAGAMI-…",text:$key).textFieldStyle(.roundedBorder).frame(width:360);Button("Продолжить"){model.run("activate",["key":key]);key=""}.buttonStyle(.borderedProminent).controlSize(.large).disabled(key.isEmpty || model.busy);Link("Получить бесплатный ключ",destination:URL(string:"https://t.me/bright26bot?start=dagami")!);if model.busy {ProgressView()};Text(model.message).font(.caption).foregroundStyle(.secondary).frame(maxWidth:500)}.frame(maxWidth:.infinity,maxHeight:.infinity).background(.regularMaterial)}
}
struct ProfileSheet:View {
    @EnvironmentObject var model:Model;@Environment(\.dismiss) var dismiss
    var profile:Profile?
    @State private var name="";@State private var useDNS=true;@State private var useProxy=false
    @State private var provider="Custom";@State private var endpoints="udp://89.22.224.205";@State private var domains="";@State private var scope="ai";@State private var url=""
    @State private var loading=true;@State private var saving=false;@State private var loaded=false;@State private var error="";@State private var visible=false
    var connectionLabel:String {guard let parts=URLComponents(string:url),let host=parts.host else{return ""};return (parts.scheme ?? "").uppercased()+" · "+host+(parts.port.map{":"+String($0)} ?? "")+(parts.user.map{" · "+$0} ?? "")}
    func load() async {
        loading=true;loaded=false;error=""
        defer{loading=false}
        guard let profile=profile else{name="ИИ — Smart DNS";loaded=true;return}
        name=profile.name
        do {
            let data=try await model.profileRequest("profileDetails",["name":profile.id])
            let details=try JSONDecoder().decode(ProfileDetails.self,from:data)
            name=details.name;useDNS=details.dns;useProxy=details.proxy;endpoints=details.endpoints.joined(separator:"\n");scope=details.scope;domains=details.domains.joined(separator:", ");url=details.url
            if details.endpoints==["udp://89.22.224.205"]{provider="Dagami UDP"}
            else if details.endpoints==["udp://2.56.175.196"]{provider="MagicDNS UDP"}
            else{provider=model.state.providers.keys.sorted().first(where:{model.state.providers[$0]==details.endpoints}) ?? "Custom"}
            loaded=true
        } catch {self.error=error.localizedDescription}
    }
    func save() {
        saving=true;error=""
        let target=name.trimmingCharacters(in:.whitespacesAndNewlines)
        let args:[String:Any]=["name":target,"replace":profile != nil,"proxy":useProxy,"dns":useDNS,"url":url,"endpoints":endpoints.split(separator:"\n").map(String.init),"scope":scope,"domains":domains.components(separatedBy:",").map{$0.trimmingCharacters(in:.whitespacesAndNewlines)}.filter{!$0.isEmpty}]
        Task {
            do{_ = try await model.profileRequest("profileSave",args);model.profile=target;model.message="Профиль сохранён.";saving=false;model.refresh();dismiss()}
            catch{self.error=error.localizedDescription;saving=false}
        }
    }
    var body:some View {
        VStack(alignment:.leading,spacing:16){
            HStack{Text(profile == nil ? "Новый профиль":"Изменить профиль").font(.title2.bold());Spacer();Button{dismiss()}label:{Image(systemName:"xmark.circle.fill").foregroundStyle(.secondary)}.buttonStyle(.plain).disabled(saving)}
            if loading {ProgressView("Загружаем сохранённые настройки…").frame(maxWidth:.infinity,minHeight:180)}
            else if !loaded {Text(error).font(.callout).foregroundStyle(.orange).textSelection(.enabled);Button("Повторить"){Task{await load()}}}
            else {
                ScrollView {
                    VStack(alignment:.leading,spacing:14){
                        TextField("Название профиля",text:$name).textFieldStyle(.roundedBorder).disabled(profile != nil)
                        Toggle("Использовать прокси",isOn:$useProxy)
                        if useProxy || (!url.isEmpty && url != "direct://") {
                            VStack(alignment:.leading,spacing:7){
                                Text("Ссылка прокси").font(.system(size:11,weight:.medium)).foregroundStyle(.secondary)
                                HStack{Group{if visible{TextField("https://логин:пароль@сервер:порт",text:$url)}else{SecureField("https://логин:пароль@сервер:порт",text:$url)}}.textFieldStyle(.roundedBorder);Button{visible.toggle()}label:{Image(systemName:visible ? "eye.slash":"eye")}.buttonStyle(.plain).help(visible ? "Скрыть ссылку":"Показать ссылку")}
                                if !connectionLabel.isEmpty{Text(connectionLabel).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)}
                                Text("Пароль хранится в Связке ключей macOS.").font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        Toggle("Использовать Smart DNS",isOn:$useDNS).onChange(of:useDNS){enabled in if enabled && endpoints.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty{endpoints="udp://89.22.224.205"}}
                        if useDNS {
                            Picker("Провайдер",selection:$provider){Text("Dagami · UDP").tag("Dagami UDP");Text("MagicDNS · UDP").tag("MagicDNS UDP");ForEach(model.state.providers.keys.sorted(),id:\.self){Text($0).tag($0)};Text("Свой DNS").tag("Custom")}.onChange(of:provider){value in guard loaded else{return};if value=="Dagami UDP"{endpoints="udp://89.22.224.205"}else if value=="MagicDNS UDP"{endpoints="udp://2.56.175.196"}else if let list=model.state.providers[value]{endpoints=list.joined(separator:"\n")}}
                            TextEditor(text:$endpoints).font(.system(.body,design:.monospaced)).frame(height:65).padding(6).background(.quaternary,in:RoundedRectangle(cornerRadius:8))
                            Picker("Домены",selection:$scope){Text("Все ИИ").tag("ai");Text("Google / Antigravity").tag("google")}
                            TextField("Свои домены через запятую",text:$domains).textFieldStyle(.roundedBorder)
                        }
                        if !useProxy && !useDNS{Text("Будет использоваться обычная сеть Mac.").font(.caption).foregroundStyle(.secondary)}
                    }.padding(.trailing,3)
                }.frame(height:330).disabled(saving)
                if !error.isEmpty{Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled)}
            }
            Divider()
            HStack{Button("Отмена"){dismiss()}.disabled(saving);Spacer();if saving{ProgressView().controlSize(.small)};Button("Сохранить"){save()}.buttonStyle(.borderedProminent).disabled(!loaded || saving || model.busy || name.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty || (useProxy && (url.isEmpty || url=="direct://")))}
        }.padding(24).frame(width:540).background(Color(nsColor:.windowBackgroundColor)).toggleStyle(.switch).task{await load()}.interactiveDismissDisabled(saving)
    }
}
struct AppsView:View {
    @EnvironmentObject var model:Model
    var compact=false
    @State var search="";@State var login=false;@State var loginURL="";@State var choose=true
    var apps:[ClientApp] {let list=compact ? model.state.apps.filter{$0.installed}:model.state.apps;return list.filter{search.isEmpty || $0.name.localizedCaseInsensitiveContains(search)}}
    var body:some View {
        Card {
            HStack{Text(compact ? "Быстрый запуск":"Приложения").font(.headline);Spacer();if !compact {Button{let panel=NSOpenPanel();panel.canChooseFiles=true;panel.canChooseDirectories=true;panel.allowsMultipleSelection=false;if panel.runModal() == .OK,let path=panel.url?.path {model.run("addApp",["path":path,"cli":!path.contains(".app")])}}label:{Image(systemName:"plus")}.help("Добавить приложение")}}
            if !compact {TextField("Найти приложение",text:$search).textFieldStyle(.roundedBorder)}
            if apps.isEmpty {Text("Приложения пока не найдены. Добавьте .app или исполняемый файл.").foregroundStyle(.secondary)}
            ForEach(apps){app in
                VStack(alignment:.leading,spacing:10) {
                    HStack(spacing:11){
                        AppGlyph(id:app.id)
                        VStack(alignment:.leading,spacing:4){Text(app.name).font(.system(size:13,weight:.semibold));Text(app.recoverable == true ? "Требуется восстановление":(app.installed ? (app.prepared ? "Подготовлено":"Найдено на Mac"):"Нужен путь к приложению")).font(.system(size:10)).foregroundStyle(.secondary)}
                        Spacer(minLength:5)
                        Button{model.client=app.id;model.run("launch",["app":app.id,"profile":model.profile])}label:{Image(systemName:"play.fill").font(.system(size:11)).frame(width:28,height:26)}.buttonStyle(.borderedProminent).disabled(!app.installed || app.launchError != nil || app.recoverable == true || model.profile.isEmpty || model.busy).help("Запустить \(app.name)").accessibilityLabel("Запустить \(app.name)")
                        Menu {
                            if ["antigravity","antigravity-ide","agy","codex","codex-gui","chatgpt"].contains(app.id) {
                                Button((app.prepared || app.recoverable == true) ? "Откатить патч":"Применить патч"){model.run((app.prepared || app.recoverable == true) ? "restore":"prepare",["app":app.id,"profile":model.profile])}.disabled((!app.installed && app.recoverable != true) || (app.launchError != nil && !app.prepared && app.recoverable != true))
                            }
                            if ["antigravity","antigravity-ide"].contains(app.id) {
                                Button("Починить IDE"){model.run("repairIDE",["app":app.id,"profile":model.profile])}
                                Button("Подготовить backend"){model.run("prepare",["app":app.id,"profile":model.profile])}
                                Button("Проверить сервер IDE"){model.run("checkIDE",["profile":model.profile])}
                                Button("Вход Google"){model.client=app.id;login=true}
                            }
                            if app.id=="chatgpt" {Button("Открыть веб-версию"){model.run("launch",["app":"chatgpt-web","profile":model.profile])}.disabled(model.profile.isEmpty)}
                            Button("Создать ярлык запуска"){model.run("shortcut",["app":app.id,"profile":model.profile])}.disabled(model.profile.isEmpty)
                            Button("Отменить подготовку"){model.run("unpatch",["app":app.id])}
                            Divider()
                            Button("Остановить сессию"){let alert=NSAlert();alert.messageText="Остановить \(app.name)?";alert.informativeText="Сохраните работу. Управляемые процессы приложения будут закрыты.";alert.addButton(withTitle:"Остановить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("stop",["app":app.id])}}
                            if app.id.hasPrefix("custom_"){Button("Удалить запись"){model.run("removeApp",["app":app.id])}}
                        }label:{Image(systemName:"ellipsis").frame(width:16)}.menuStyle(.borderlessButton).fixedSize().disabled(model.busy).help("Патч и другие действия")
                    }
                    if !compact && ["antigravity","antigravity-ide","agy","codex","codex-gui","chatgpt"].contains(app.id) {
                        HStack(spacing:8){
                            Button{model.run((app.prepared || app.recoverable == true) ? "restore":"prepare",["app":app.id,"profile":model.profile])}label:{Label((app.prepared || app.recoverable == true) ? "Откатить патч":"Применить патч",systemImage:app.prepared ? "arrow.uturn.backward":"wand.and.stars")}.disabled((!app.installed && app.recoverable != true) || model.busy || (app.launchError != nil && !app.prepared && app.recoverable != true))
                            if ["antigravity","antigravity-ide"].contains(app.id) {Button{model.run("repairIDE",["app":app.id,"profile":model.profile])}label:{Label("Починить IDE",systemImage:"wrench.and.screwdriver")}.disabled((!app.installed && !app.prepared) || model.busy)}
                        }.font(.system(size:11)).buttonStyle(SoftButton()).padding(.leading,53)
                    }
                    if let reason=app.preparationError {Text(reason).font(.caption).foregroundStyle(.orange).fixedSize(horizontal:false,vertical:true)}
                    if let reason=app.launchError {Text(reason).font(.caption).foregroundStyle(.orange).fixedSize(horizontal:false,vertical:true)}
                }.padding(.vertical,3)
                if app.id != apps.last?.id {Divider().opacity(0.55)}
            }

        }.sheet(isPresented:$login){VStack(alignment:.leading,spacing:20){Text("Вход Google").font(.title2.bold());Text("Начните вход в Antigravity и вставьте свежую ссылку accounts.google.com. Она откроется через активную сессию приложения.").foregroundStyle(.secondary);SecureField("Ссылка входа",text:$loginURL).textFieldStyle(.roundedBorder);Toggle("Предложить выбор аккаунта",isOn:$choose);HStack{Button("Отмена"){login=false};Button("Найти ссылку"){Task{if let data=try? await model.rpc.call("loginURL"),let reply=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {loginURL=reply["result"] as? String ?? ""}}};Button("Копировать"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(loginURL,forType:.string)}.disabled(loginURL.isEmpty);Spacer();Button("Открыть вход"){model.run("login",["app":model.client,"url":loginURL,"choose":choose]);login=false;loginURL=""}.buttonStyle(.borderedProminent).disabled(loginURL.isEmpty)}}.padding(28).frame(width:500)}
    }
}
struct SystemDNSView:View {
    @EnvironmentObject var model:Model
    @State var server="89.22.224.205";@State var mode="domains";@State var services=Set<String>();@State var replace=false
    var body:some View {VStack(spacing:20){Card{HStack{Image(systemName:"network").font(.largeTitle).foregroundStyle(.blue);VStack(alignment:.leading,spacing:5){Text("DNS в macOS").font(.title2.bold());Text("Текущее состояние: \(model.state.systemDNS)").foregroundStyle(.secondary)}};Text("Рекомендуется режим «Только домены ИИ»: обычные сайты используют DNS вашей сети. Изменения применяются к сети Mac. Перед записью сохраняется копия; для изменения настроек macOS запросит права администратора.").font(.callout).foregroundStyle(.secondary)
            Button("Исправить загрузку страниц в браузере"){let alert=NSAlert();alert.messageText="Разделить DNS для ИИ и обычных сайтов?";alert.informativeText="Прежний общий DNS будет восстановлен из копии. Если выбранный Smart DNS всё ещё является единственным общим сервером, подключение вернётся к автоматическому DNS сети. Для доменов ИИ сохранятся отдельные правила. macOS запросит права администратора.";alert.addButton(withTitle:"Исправить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("systemDNS",["operation":"apply","server":server,"mode":"domains","services":[],"replace":replace,"restore_global":true])}}.buttonStyle(.borderedProminent).disabled(model.busy)
            TextField("IP DNS-сервера",text:$server).textFieldStyle(.roundedBorder)
            Picker("Режим",selection:$mode){Text("Выбранные подключения").tag("adapters");Text("Только домены ИИ").tag("domains")}.pickerStyle(.segmented)
            if mode=="adapters" {ForEach(model.state.services){service in Toggle(service.name,isOn:Binding(get:{services.contains(service.id)},set:{if $0 {services.insert(service.id)} else {services.remove(service.id)}}))};if model.state.services.isEmpty{Text("Подключения не найдены. Нажмите обновление.").foregroundStyle(.secondary)}}
            Toggle("Разрешить замену конфликтующих правил с копией",isOn:$replace)
            HStack{Button("Применить DNS"){let alert=NSAlert();alert.messageText="Применить DNS к macOS?";alert.informativeText="Сервер: \(server). Выбранные подключения: \(services.sorted().joined(separator:", ")). macOS запросит права администратора.";alert.addButton(withTitle:"Применить");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("systemDNS",["operation":"apply","server":server,"mode":mode,"services":Array(services),"replace":replace,"restore_global":mode=="domains"])}}.buttonStyle(.borderedProminent).disabled(model.busy || (mode=="adapters" && services.isEmpty));Button("Восстановить прежний DNS"){model.run("systemDNS",["operation":"restore"])}.disabled(model.busy)}
        };Card{Label("Ethernet и Wi-Fi",systemImage:"cable.connector").font(.headline);Text("Список считывается из macOS. Для общего DNS отметьте реальное подключение, через которое работает интернет. Профиль Smart DNS и системный DNS настраиваются отдельно.").foregroundStyle(.secondary)}}}
}

struct JournalView:View {
    @EnvironmentObject var model:Model
    @State private var onlyErrors=false;@State private var search=""
    var filtered:[JournalEntry] {model.events.filter{(!onlyErrors || !$0.success) && (search.isEmpty || ($0.title+" "+$0.summary+" "+$0.detail).localizedCaseInsensitiveContains(search))}}
    var body:some View {
        VStack(spacing:12){
            HStack{Toggle("Только ошибки",isOn:$onlyErrors).font(.system(size:12));Spacer();Button{model.run("journalEntries",refresh:false)}label:{Image(systemName:"arrow.clockwise")}.help("Обновить журнал").disabled(model.busy);Button("Копировать всё"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(model.events.map{$0.time+" · "+$0.title+"\n"+$0.summary+"\n"+$0.detail}.joined(separator:"\n\n"),forType:.string)}.disabled(model.events.isEmpty)}
            TextField("Поиск в журнале",text:$search).textFieldStyle(.roundedBorder)
            if filtered.isEmpty {Card{Label(model.events.isEmpty ? "Здесь появятся события":"Ничего не найдено",systemImage:"text.alignleft").font(.headline);Text("Запуски, проверки и ошибки будут показаны с понятным описанием.").font(.caption).foregroundStyle(.secondary)}}
            LazyVStack(spacing:10){ForEach(filtered){entry in
                Card {
                    HStack(alignment:.top,spacing:10){Image(systemName:entry.success ? "checkmark.circle.fill":"exclamationmark.circle.fill").font(.system(size:19)).foregroundStyle(entry.success ? Color.green:Color.orange);VStack(alignment:.leading,spacing:4){Text(entry.title).font(.system(size:13,weight:.semibold));Text(entry.displayTime).font(.system(size:10)).foregroundStyle(.secondary)};Spacer();Text(entry.success ? "Готово":"Ошибка").font(.system(size:10,weight:.medium)).foregroundStyle(entry.success ? Color.green:Color.orange)}
                    Text(entry.summary).font(.system(size:12)).textSelection(.enabled)
                    DisclosureGroup("Технические подробности") {
                        VStack(alignment:.leading,spacing:8){Text(entry.detail).font(.system(size:10,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading);Button("Копировать событие"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(entry.time+" · "+entry.title+"\n"+entry.detail,forType:.string)}}.padding(.top,6)
                    }.font(.system(size:11)).foregroundStyle(.secondary)
                }
            }}
            Link("Сообщить об ошибке на GitHub",destination:URL(string:"https://github.com/ImRealDerli/Dagami-Agent-Proxy-macOS/issues")!).font(.caption)
        }.onAppear{model.run("journalEntries",refresh:false)}
    }
}

struct LicenseSettingsView:View {
    @EnvironmentObject var model:Model
    @State var key=""
    var body:some View {Card{
        Label("Активация Dagami",systemImage:"key.horizontal").font(.headline)
        Text(model.state.activated ? "Ключ активирован":"Нужна активация").foregroundStyle(.secondary)
        SecureField("Новый ключ доступа DAGAMI-…",text:$key).textFieldStyle(.roundedBorder)
        HStack{Button("Активировать ключ"){model.run("activate",["key":key]);key=""}.disabled(key.isEmpty || model.busy)
            Button("Сбросить ключ",role:.destructive){let alert=NSAlert();alert.messageText="Сбросить ключ активации Dagami?";alert.informativeText="После сброса потребуется повторная активация. Текущая сессия входа через браузер будет закрыта. Профили, пароли прокси и аккаунты ИИ сохранятся.";alert.addButton(withTitle:"Сбросить ключ");alert.addButton(withTitle:"Отмена");if alert.runModal() == .alertFirstButtonReturn {model.run("licenseReset")}}.disabled(model.busy)
        }.buttonStyle(.bordered)
        Link("Получить ключ",destination:URL(string:"https://t.me/bright26bot?start=dagami")!)
    }}
}

struct AuthView:View {
    @EnvironmentObject var model:Model
    @State var service="codex";@State var mode="cli";@State var auto=true;@State var inputURL=""
    let services=[("codex","Codex / ChatGPT"),("claude","Claude / Claude Code"),("antigravity","Antigravity App"),("antigravity-ide","Antigravity IDE — VS Code"),("agy","Antigravity CLI"),("gemini","Gemini / Google AI"),("deepseek","DeepSeek"),("qwen","Qwen"),("grok","Grok"),("perplexity","Perplexity"),("mistral","Mistral"),("copilot","Microsoft Copilot"),("openrouter","OpenRouter"),("custom","Другой ИИ — своя ссылка")]
    func start() {
        if model.auth.running {
            let alert=NSAlert();alert.messageText="Начать новую сессию входа?";alert.informativeText="Предыдущий браузер входа будет закрыт. Сохранённые аккаунты клиентов не удаляются.";alert.addButton(withTitle:"Начать");alert.addButton(withTitle:"Отмена");if alert.runModal() != .alertFirstButtonReturn {return}
        }
        model.run("authStart",["service":service,"profile":model.profile,"mode":mode,"auto":auto,"url":service=="custom" ? inputURL:""] ,refresh:false)
    }
    var body:some View {VStack(spacing:20){
        Card{
            Label("Вход через выбранный профиль",systemImage:"person.crop.circle.badge.checkmark").font(.headline)
            Picker("Профиль",selection:$model.profile){ForEach(model.state.profiles){Text($0.name).tag($0.id)}}
            HStack(spacing:10){AppGlyph(id:service,small:true);Picker("ИИ-сервис",selection:$service){ForEach(services,id:\.0){Text($0.1).tag($0.0)}}}.onChange(of:service){value in mode=(value=="codex" || value=="claude") ? "cli":((value=="antigravity" || value=="antigravity-ide" || value=="agy") ? "watch":"browser");inputURL=""}
            Button("Проверить маршрут входа"){model.run("probeAuth",["profile":model.profile,"service":service,"url":service=="custom" ? inputURL:""],refresh:false)}.disabled(model.profile.isEmpty || model.busy)
            if !model.authNetworkStatus.isEmpty {Text(model.authNetworkStatus).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)}
            Toggle("Подхватывать OAuth-ссылки из буфера обмена",isOn:$model.clipboardEnabled)
            Text("Работает только во время ожидания входа и только для выбранного профиля. Принимаются исходные OAuth-ссылки с проверенным доменом, client_id, state и callback. Адреса accountchooser/consent из браузера не открываются повторно.").font(.caption).foregroundStyle(.secondary)
            if service=="agy" {Text("Откройте CLI кнопкой ниже. Selenium получит код с официальной страницы возврата и передаст его в ожидающий CLI с Enter. Состояние OAuth проверяется; ручной ввод не перезаписывается.").font(.callout).foregroundStyle(.secondary)}
            if service=="agy" {Button("Открыть CLI с перехватом входа"){model.run("launch",["app":"agy","profile":model.profile])}.buttonStyle(.borderedProminent).disabled(model.profile.isEmpty || model.busy)}
            Picker("Способ входа",selection:$mode){if service != "antigravity" && service != "antigravity-ide" && service != "agy" {Text("Сайт в браузере").tag("browser")};if service=="codex" || service=="claude" {Text("Штатный вход CLI").tag("cli")};if service=="codex" {Text("Код устройства").tag("device")};if service != "custom" {Text(["antigravity","antigravity-ide"].contains(service) ? "Вход в Antigravity":"Подхват из приложения").tag("watch")}}
            if service != "agy" {Text(mode=="cli" ? "Dagami запустит штатную команду входа клиента, подхватит ссылку и откроет её через тот же профиль. Вход завершается в самом клиенте.":(mode=="device" ? "Для Codex может потребоваться включить вход по коду устройства в настройках безопасности ChatGPT.":(["antigravity","antigravity-ide"].contains(service) ? "Для входа IDE нужна её собственная свежая ссылка. Dagami откроет её через профиль активной сессии.":(mode=="watch" ? "Нажмите «Начать вход», затем начните авторизацию в IDE или CLI. Новые ссылки из поддерживаемых журналов будут подхвачены автоматически в течение 10 минут.":"Веб-вход создаёт сессию в отдельном браузере. Для входа CLI выберите штатный вход CLI.")))).font(.callout).foregroundStyle(.secondary)}
            if ["antigravity","antigravity-ide"].contains(service) {
                Text("Сначала один раз настройте вход в IDE. Затем нажмите «Начать вход» здесь и «Войти» в Antigravity. Ссылка откроется через маршрут самой IDE.").font(.callout).foregroundStyle(.secondary)
                Button("Настроить вход в IDE") {model.run("prepareAuth",["profile":model.profile,"app":service])}.disabled(model.profile.isEmpty || model.busy)
            }
            if !["antigravity","antigravity-ide"].contains(service) {Toggle("Автоматически открывать найденную ссылку",isOn:$auto)}
            if service=="custom" {TextField("HTTPS-ссылка страницы входа",text:$inputURL).textFieldStyle(.roundedBorder);Text("Проверьте домен сервиса перед входом.").font(.caption).foregroundStyle(.secondary)}
            HStack{if service != "agy" {Button("Начать вход"){start()}.buttonStyle(.borderedProminent).disabled(model.profile.isEmpty || model.busy || (service=="custom" && inputURL.isEmpty))};Button("Остановить сессию"){model.run("authStop",refresh:false)}.disabled(!model.auth.running || model.busy)}
        }
        Card{
            Text("Ссылка авторизации").font(.headline)
            SecureField("Свежая ссылка из клиента или браузера",text:$inputURL).textFieldStyle(.roundedBorder)
            HStack{Button("Найти ссылку"){model.run("authFind",["service":service,"profile":model.profile],refresh:false)}.disabled(service=="custom" || model.busy);Button("Открыть через профиль"){if model.auth.running && model.auth.service==service && model.auth.profile==model.profile {model.run("authOpen",["url":inputURL],refresh:false)} else {model.run("authStart",["service":service,"profile":model.profile,"mode":"browser","auto":auto,"url":inputURL],refresh:false)}}.disabled(inputURL.isEmpty || model.profile.isEmpty || model.busy);Button("Копировать"){NSPasteboard.general.clearContents();NSPasteboard.general.setString(inputURL,forType:.string)}.disabled(inputURL.isEmpty)}
            if !model.auth.code.isEmpty {Text("Код устройства: "+model.auth.code).font(.system(.title3,design:.monospaced)).textSelection(.enabled)}
            if let activeProfile=model.auth.profile,model.auth.running {Text("Маршрут активной сессии: "+activeProfile).font(.caption).foregroundStyle(.secondary)}
            Text(model.auth.message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            Text("Пароли вводятся только на сайте сервиса. Ссылки и коды входа не записываются в журнал Dagami. Доступ к модели проверяется отдельно.").font(.caption).foregroundStyle(.secondary)
        }
    }.onAppear{if ["antigravity","antigravity-ide","agy"].contains(model.client){service=model.client;mode="watch"}}.onChange(of:model.auth.url){value in if !value.isEmpty {inputURL=value}}
    .task{while !Task.isCancelled {do{try await Task.sleep(nanoseconds:2_000_000_000)}catch{return};if model.auth.running && !model.busy {model.run("authStatus",refresh:false)}}}
    }
}

struct ProfilesView:View {
    @EnvironmentObject var model:Model
    @State private var search="";@State private var kind="Все";@State private var editor:ProfileEditorTarget?
    var filtered:[Profile] {model.state.profiles.filter{(search.isEmpty || $0.name.localizedCaseInsensitiveContains(search)) && (kind=="Все" || (kind=="DNS" && $0.dns) || (kind=="Прокси" && $0.proxy))}}
    func remove(_ profile:Profile) {
        let alert=NSAlert();alert.messageText="Удалить «\(profile.name)»?";alert.informativeText="Профиль и его сохранённый пароль будут удалены. Открытые сессии этого профиля нужно сначала остановить."
        alert.alertStyle = .warning;alert.addButton(withTitle:"Удалить");alert.addButton(withTitle:"Отмена")
        if alert.runModal() == .alertFirstButtonReturn {model.run("profileDelete",["name":profile.id])}
    }
    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            HStack(alignment:.top,spacing:10){
                VStack(alignment:.leading,spacing:4){Text("Выбранный профиль").font(.system(size:10)).foregroundStyle(.secondary);Text(model.chosen?.name ?? "Пока не выбран").font(.system(size:14,weight:.semibold)).lineLimit(2)}
                Spacer()
                Button{editor=ProfileEditorTarget(profile:nil)}label:{Label("Добавить",systemImage:"plus")}.buttonStyle(.borderedProminent).disabled(model.busy)
            }
            HStack(spacing:12){TextField("Найти профиль",text:$search).textFieldStyle(.roundedBorder);Picker("Тип профиля",selection:$kind){Text("Все").tag("Все");Text("DNS").tag("DNS");Text("Прокси").tag("Прокси")}.pickerStyle(.segmented).labelsHidden().frame(width:215)}
            LazyVStack(spacing:9){ForEach(filtered){profile in
                ProfileChoiceRow(profile:profile,selected:model.profile==profile.id,select:{model.profile=profile.id},edit:{editor=ProfileEditorTarget(profile:profile)},delete:{remove(profile)}).disabled(model.busy)
            }}
            if filtered.isEmpty {Card{Label(model.state.profiles.isEmpty ? "Добавьте первый профиль":"Нет подходящих профилей",systemImage:"slider.horizontal.3").font(.headline);Text(model.state.profiles.isEmpty ? "Выберите Smart DNS без пароля или вставьте ссылку прокси.":"Измените поиск или выберите «Все».").font(.caption).foregroundStyle(.secondary)}}
            Text("Выбранный профиль используется для новых запусков. Уже открытые сессии сохраняют свой маршрут.").font(.system(size:11)).foregroundStyle(.secondary)
        }.onAppear{if let id=ProcessInfo.processInfo.environment["DAGAMI_UI_EDIT_PROFILE"],ProcessInfo.processInfo.environment["DAGAMI_UI_PREVIEW"] == "1",let profile=model.state.profiles.first(where:{$0.id==id}){editor=ProfileEditorTarget(profile:profile)}}.sheet(item:$editor){target in ProfileSheet(profile:target.profile).environmentObject(model)}
    }
}
struct ProfileChoiceRow:View {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var profile:Profile;var selected:Bool;var select:()->Void;var edit:()->Void;var delete:()->Void
    var body:some View {
        HStack(spacing:0) {
            Button(action:select){
                HStack(spacing:12){
                    Image(systemName:profile.dns ? "globe":"shield.lefthalf.filled").font(.system(size:20)).foregroundStyle(profile.dns ? Color.blue:Color.indigo).frame(width:40,height:40).background((profile.dns ? Color.blue:Color.indigo).opacity(0.09),in:RoundedRectangle(cornerRadius:12))
                    VStack(alignment:.leading,spacing:5){Text(profile.name).font(.system(size:13,weight:.semibold)).lineLimit(2).foregroundStyle(.primary);Text(profile.subtitle).font(.system(size:11)).foregroundStyle(.secondary)}
                    Spacer(minLength:8)
                    ZStack{Image(systemName:"circle").foregroundStyle(.secondary.opacity(0.4));Image(systemName:"checkmark.circle.fill").foregroundStyle(.blue).opacity(selected ? 1:0)}.font(.system(size:21)).animation(reduceMotion ? nil:.easeOut(duration:0.12),value:selected)
                }.padding(14).contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityLabel(profile.name+", "+profile.subtitle).accessibilityValue(selected ? "Выбран":"Не выбран")
            Divider().frame(height:24)
            Button(action:edit){Image(systemName:"slider.horizontal.3").font(.system(size:14)).frame(width:40,height:40).contentShape(Rectangle())}.buttonStyle(.plain).help("Изменить "+profile.name).accessibilityLabel("Изменить "+profile.name)
            Button(action:delete){Image(systemName:"trash").font(.system(size:13)).foregroundStyle(.secondary).frame(width:32,height:40).contentShape(Rectangle())}.buttonStyle(.plain).padding(.trailing,5).help("Удалить "+profile.name).accessibilityLabel("Удалить "+profile.name)
        }.background(selected ? Color.blue.opacity(0.06):Color(nsColor:.controlBackgroundColor),in:RoundedRectangle(cornerRadius:15,style:.continuous))
            .overlay(RoundedRectangle(cornerRadius:15,style:.continuous).strokeBorder(selected ? Color.blue.opacity(0.65):Color.primary.opacity(0.06),lineWidth:1))
    }
}
struct ConnectionCheckView:View {
    @EnvironmentObject var model:Model
    var body:some View {
        Card {
            HStack(spacing:10){
                if model.checkingConnection {ProgressView().controlSize(.small)}
                else {Image(systemName:model.connectionReport?.success == true ? "checkmark.circle.fill":"exclamationmark.circle.fill").foregroundStyle(model.connectionReport?.success == true ? Color.green:Color.orange)}
                VStack(alignment:.leading,spacing:3){Text(model.checkingConnection ? "Проверяем подключение…":"Результат проверки").font(.system(size:13,weight:.semibold));Text(model.connectionProfile).font(.system(size:10)).foregroundStyle(.secondary)}
                Spacer()
                if model.checkingConnection {TimelineView(.periodic(from:model.checkStarted,by:1)){context in Text("\(max(0,Int(context.date.timeIntervalSince(model.checkStarted)))) с").monospacedDigit().font(.system(size:11)).foregroundStyle(.secondary)}}
                else {Button{model.showConnectionPanel=true}label:{Image(systemName:"arrow.up.left.and.arrow.down.right")}.buttonStyle(.plain).help("Открыть проверку");Button{model.connectionReport=nil}label:{Image(systemName:"xmark")}.buttonStyle(.plain).help("Скрыть результат")}
            }
            if model.checkingConnection {Text("Проверяем защищённый TLS-туннель к сервисам. Это может занять до минуты.").font(.system(size:11)).foregroundStyle(.secondary)}
            if let report=model.connectionReport {
                ForEach(report.targets){target in
                    HStack(alignment:.top,spacing:8){Image(systemName:target.success ? "checkmark":"exclamationmark.triangle").foregroundStyle(target.success ? Color.green:Color.orange).font(.system(size:11));VStack(alignment:.leading,spacing:3){Text(target.name).font(.system(size:12));if let error=target.error,!target.success {Text(error).font(.system(size:10)).foregroundStyle(.secondary).textSelection(.enabled)}};Spacer();if let ms=target.latency_ms {Text("\(Int(ms)) мс").font(.system(size:10)).monospacedDigit().foregroundStyle(.secondary)}}
                }
                if report.targets.isEmpty {ForEach(report.errors,id:\.self){Text($0).font(.system(size:11)).foregroundStyle(.orange).textSelection(.enabled)}}
            }
        }
    }
}
struct SessionsView:View {
    @EnvironmentObject var model:Model
    @State private var showQuotaDesign=false
    func stop(_ session:ManagedSession) {
        let alert=NSAlert();alert.messageText="Остановить «\(session.name)»?";alert.informativeText=session.terminal == true ? "Сохраните работу. Будет завершена только выбранная CLI-сессия и её дочерние процессы.":"Сохраните работу. Приложение, его управляемые фоновые процессы и браузер входа будут закрыты."
        alert.addButton(withTitle:"Остановить");alert.addButton(withTitle:"Отмена")
        if alert.runModal() == .alertFirstButtonReturn {model.run("stop",["app":session.id],refresh:false)}
    }
    var body:some View {
        VStack(spacing:12){
            HStack{Text("Управляемые сессии: \(model.sessions.count)").font(.system(size:12)).foregroundStyle(.secondary);Spacer();if designTest{Button{showQuotaDesign=true}label:{Label("Вид лимитов",systemImage:"sparkles")}};Button{model.run("sessions",refresh:false)}label:{Label("Обновить",systemImage:"arrow.clockwise")}.disabled(model.busy)}
            if model.sessions.isEmpty {Card{Label("Нет открытых сессий",systemImage:"rectangle.stack").font(.headline);Text("Запустите приложение через Dagami — здесь появятся его профиль, маршрут и состояние.").font(.caption).foregroundStyle(.secondary);Button("К приложениям"){model.page="Приложения"}.buttonStyle(.borderedProminent)}}
            LazyVStack(spacing:10){ForEach(model.sessions){session in
                Card {
                    HStack(spacing:11){AppGlyph(id:session.app ?? session.id);VStack(alignment:.leading,spacing:4){Text(session.name).font(.system(size:13,weight:.semibold));Label(session.status,systemImage:session.running ? "circle.fill":"circle").font(.system(size:10)).foregroundStyle(!session.error.isEmpty ? Color.orange:(session.running ? Color.green:Color.secondary))};Spacer();Button("Остановить"){stop(session)}.disabled(model.busy || session.stopping || session.canStop == false)}
                    HStack{Label(session.profile.isEmpty ? "Профиль недоступен":session.profile,systemImage:"slider.horizontal.3").font(.system(size:12));Spacer();if session.browser {Label("Вход",systemImage:"person.crop.circle").font(.system(size:10)).foregroundStyle(.secondary)}}
                    SessionInsights(session:session)
                    if let notice=session.notice,!notice.isEmpty {Text(notice).font(.caption).foregroundStyle(.secondary)}
                    if !session.error.isEmpty {Text(session.error).font(.caption).foregroundStyle(.orange).textSelection(.enabled)}
                    DisclosureGroup("Подробности маршрута") {VStack(alignment:.leading,spacing:5){if let engine=session.networkEngine{Text("Сетевой транспорт: "+engine)}else{Text("Для нового транспорта перезапустите сессию через Dagami.")};if !session.bridge.isEmpty {Text(session.bridge)};if session.pid>0 {Text("Контроллер: \(session.pid)")};if !session.pids.isEmpty {Text("Процессы: "+session.pids.map{String($0)}.joined(separator:", "))}}.font(.system(size:10,design:.monospaced)).textSelection(.enabled).frame(maxWidth:.infinity,alignment:.leading)}.font(.system(size:11)).foregroundStyle(.secondary)
                }
            }}
            if model.auth.running {Card{Label("Сессия входа",systemImage:"person.crop.circle").font(.headline);Text((model.auth.service ?? "ИИ")+" · "+(model.auth.profile ?? "")).font(.caption);Text(model.auth.message).font(.caption).foregroundStyle(.secondary);Button("Завершить вход"){model.run("authStop",refresh:false)}.disabled(model.busy)}}
        }.onAppear{if designTest && ProcessInfo.processInfo.environment["DAGAMI_UI_GALLERY"]=="1"{showQuotaDesign=true}}.sheet(isPresented:$showQuotaDesign){QuotaDesignGallery()}.task {
            if !model.busy {model.run("sessions",refresh:false)}
            while !Task.isCancelled {do{try await Task.sleep(nanoseconds:5_000_000_000)}catch{return};if !model.busy {model.run("sessions",refresh:false)}}
        }
    }
}

struct PageTabs:View {
    @EnvironmentObject var model:Model
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var items:[(String,String)]
    var body:some View {
        HStack(spacing:4){ForEach(items,id:\.0){item in
            Button{model.page=item.0}label:{Label(item.0,systemImage:item.1).font(.system(size:12,weight:model.page==item.0 ? .semibold:.regular)).padding(.vertical,9).frame(maxWidth:.infinity).foregroundStyle(model.page==item.0 ? Color.primary:Color.secondary).background(model.page==item.0 ? Color(nsColor:.controlBackgroundColor):.clear,in:RoundedRectangle(cornerRadius:9,style:.continuous)).contentShape(Rectangle())}.buttonStyle(.plain).accessibilityValue(model.page==item.0 ? "Выбрано":"")
        }}.padding(4).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:12,style:.continuous))
    }
}
struct ConnectionRadar:View {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var active:Bool;var success:Bool;var started:Date
    var tint:Color {active ? .blue:(success ? .green:.orange)}
    var body:some View {
        ZStack {
            TimelineView(.animation(minimumInterval:1.0/30,paused:reduceMotion || !active)){timeline in
                Canvas {context,size in
                    let center=CGPoint(x:size.width/2,y:size.height/2)
                    let elapsed=active && !reduceMotion ? timeline.date.timeIntervalSince(started):0
                    for index in 0..<3 {
                        let radius=CGFloat(45+index*20)
                        let rect=CGRect(x:center.x-radius,y:center.y-radius,width:radius*2,height:radius*2)
                        context.stroke(Path(ellipseIn:rect),with:.color(tint.opacity(0.10)),lineWidth:1)
                    }
                    if active {
                        let phase=reduceMotion ? 0.4:(elapsed/2).truncatingRemainder(dividingBy:1)
                        let radius=CGFloat(39+phase*46)
                        context.stroke(Path(ellipseIn:CGRect(x:center.x-radius,y:center.y-radius,width:radius*2,height:radius*2)),with:.color(tint.opacity((1-phase)*0.28)),lineWidth:2)
                        var arc=Path();arc.addArc(center:center,radius:66,startAngle:.degrees(elapsed*90),endAngle:.degrees(elapsed*90+90),clockwise:false)
                        context.stroke(arc,with:.color(tint.opacity(0.85)),style:StrokeStyle(lineWidth:3,lineCap:.round))
                    }
                    for index in 0..<4 {
                        let angle=Double(index)*Double.pi/2-Double.pi/2
                        let point=CGPoint(x:center.x+cos(angle)*66,y:center.y+sin(angle)*66)
                        let pulse=active && !reduceMotion ? 0.45+0.55*(sin(elapsed*3-Double(index))+1)/2:1
                        context.fill(Path(ellipseIn:CGRect(x:point.x-4,y:point.y-4,width:8,height:8)),with:.color(tint.opacity(pulse)))
                    }
                }
            }
            Circle().fill(tint.opacity(0.08)).frame(width:74,height:74)
            Image(systemName:active ? "network":(success ? "checkmark":"exclamationmark")).font(.system(size:31,weight:.medium)).foregroundStyle(tint)
        }.frame(width:190,height:190).accessibilityLabel(active ? "Идёт проверка связи":(success ? "Связь проверена":"Проверка обнаружила ошибки"))
    }
}
struct ConnectionPanel:View {
    @EnvironmentObject var model:Model
    var successful:Bool {model.connectionReport?.success == true}
    var title:String {model.checkingConnection ? "Проверяем связь":(successful ? "Всё на связи":"Есть проблемы со связью")}
    var body:some View {
        VStack(spacing:0){
            HStack{Text("Проверка подключения").font(.system(size:12,weight:.semibold)).foregroundStyle(.secondary);Spacer();Button{model.showConnectionPanel=false}label:{Image(systemName:"xmark.circle.fill").font(.system(size:18)).foregroundStyle(.secondary)}.buttonStyle(.plain).help(model.checkingConnection ? "Свернуть проверку":"Закрыть")}.padding(.bottom,4)
            ConnectionRadar(active:model.checkingConnection,success:successful,started:model.checkStarted)
            Text(title).font(.system(size:23,weight:.bold,design:.rounded)).padding(.top,2)
            Text(model.connectionProfile).font(.system(size:12)).foregroundStyle(.secondary).lineLimit(2).padding(.top,6)
            if model.checkingConnection {
                Text("Проверяем защищённое соединение\nс Google AI, OpenAI, Anthropic и GitHub.").font(.system(size:12)).multilineTextAlignment(.center).foregroundStyle(.secondary).padding(.top,15)
                HStack(spacing:8){ForEach(["gemini","openai","claude","github"],id:\.self){name in BrandImage(name:name).frame(width:20,height:20).frame(width:39,height:39).background(Color.primary.opacity(0.04),in:RoundedRectangle(cornerRadius:11))}}.padding(.top,17)
                TimelineView(.periodic(from:model.checkStarted,by:1)){context in Text("\(max(0,Int(context.date.timeIntervalSince(model.checkStarted)))) с · можно свернуть и продолжить работу").font(.system(size:10)).monospacedDigit().foregroundStyle(.secondary)}.padding(.top,16)
            } else if let report=model.connectionReport {
                ScrollView {
                    VStack(alignment:.leading,spacing:13){ForEach(report.targets){target in
                        HStack(alignment:.top,spacing:9){Image(systemName:target.success ? "checkmark.circle.fill":"exclamationmark.circle.fill").foregroundStyle(target.success ? Color.green:Color.orange);VStack(alignment:.leading,spacing:3){Text(target.name).font(.system(size:12,weight:.medium));if let error=target.error,!target.success {Text(error).font(.system(size:10)).foregroundStyle(.secondary).textSelection(.enabled)}};Spacer();if let ms=target.latency_ms {Text("\(Int(ms)) мс").font(.system(size:10)).monospacedDigit().foregroundStyle(.secondary)}}
                    };if report.targets.isEmpty {ForEach(report.errors,id:\.self){Text($0).font(.system(size:11)).foregroundStyle(.orange).textSelection(.enabled)}}}.padding(14)
                }.frame(maxHeight:175).background(Color.primary.opacity(0.025),in:RoundedRectangle(cornerRadius:13)).padding(.top,19)
            }
            Button{model.showConnectionPanel=false}label:{Text(model.checkingConnection ? "Свернуть":"Готово").font(.system(size:13,weight:.semibold)).frame(maxWidth:.infinity).padding(.vertical,7)}.buttonStyle(.borderedProminent).padding(.top,22)
        }.padding(24).frame(width:420).background(Color(nsColor:.windowBackgroundColor))
    }
}

struct QuotaRing:View {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var remaining:Double?
    var colors:[Color]
    var disabled:Bool
    @State private var progress:Double=0
    var body:some View {
        ZStack {
            Circle().stroke(Color.primary.opacity(0.065),lineWidth:7)
            if remaining != nil {
                if progress>0 {Circle().trim(from:0,to:progress).stroke(AngularGradient(colors:colors+[colors[0]],center:.center,startAngle:.degrees(0),endAngle:.degrees(360)),style:StrokeStyle(lineWidth:7,lineCap:.round)).rotationEffect(.degrees(-90))}
            } else {Circle().stroke(Color.secondary.opacity(0.16),style:StrokeStyle(lineWidth:1,dash:[2,5])).padding(6)}
            Circle().fill(colors[0].opacity(0.09)).padding(13)
            Image(systemName:disabled ? "pause.fill":(remaining == nil ? "minus":(remaining==0 ? "bolt.slash.fill":"bolt.fill"))).font(.system(size:20,weight:.medium)).foregroundStyle(colors[0])
        }.frame(width:73,height:73).padding(4).accessibilityHidden(true)
            .onAppear{update()}.onChange(of:remaining){_ in update()}
    }
    func update(){withAnimation(reduceMotion ? nil:.timingCurve(0.2,0.8,0.2,1,duration:0.75)){progress=(remaining ?? 0)/100}}
}
struct QuotaValue:View {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    var value:String
    var percent:Bool
    @ViewBuilder var digits:some View {
        if #available(macOS 14.0,*) {Text(value).contentTransition(.numericText())}
        else {Text(value)}
    }
    var body:some View {
        HStack(alignment:.firstTextBaseline,spacing:2){digits.font(.system(size:38,weight:.semibold,design:.rounded)).tracking(-1.8).monospacedDigit();if percent{Text("%").font(.system(size:18,weight:.medium,design:.rounded)).foregroundStyle(.secondary)}}
            .animation(reduceMotion ? nil:.easeOut(duration:0.35),value:value).lineLimit(1).minimumScaleFactor(0.65)
    }
}
struct QuotaMetricCard:View {
    @Environment(\.colorScheme) var scheme
    var quota:QuotaWindow
    var service:String
    var now:Date
    var remaining:Double? {guard quota.disabled != true,let used=quota.usedPercent,used.isFinite,(0...100).contains(used) else{return nil};return 100-used}
    var amount:Double? {guard quota.disabled != true,let value=quota.remainingAmount,value.isFinite,value>=0 else{return nil};return value}
    var exhausted:Bool {remaining==0 || (remaining==nil && amount==0)}
    var ringRemaining:Double? {remaining ?? (amount==0 ? 0:nil)}
    var expired:Bool {quota.resetAt.map{ $0<=now.timeIntervalSince1970 } ?? false}
    var colors:[Color] {
        if quota.disabled == true || (remaining == nil && amount == nil){return [.secondary,.secondary.opacity(0.55)]}
        if exhausted || (remaining.map{$0<=10} ?? false) {if scheme == .light{return [Color(red:0.77,green:0.16,blue:0.24),Color(red:0.66,green:0.12,blue:0.34)]};return [Color(red:1,green:0.38,blue:0.42),Color(red:0.89,green:0.24,blue:0.53)]}
        if let value=remaining,value<=25 {if scheme == .light{return [Color(red:0.70,green:0.35,blue:0.03),Color(red:0.82,green:0.22,blue:0.08)]};return [Color(red:1,green:0.72,blue:0.27),Color(red:1,green:0.43,blue:0.29)]}
        if service.hasPrefix("codex") {if scheme == .light{return [Color(red:0.08,green:0.48,blue:0.36),Color(red:0.08,green:0.43,blue:0.58)]};return [Color(red:0.24,green:0.78,blue:0.61),Color(red:0.14,green:0.66,blue:0.78)]}
        if quota.label.lowercased().contains("claude") || service=="claude" {if scheme == .light{return [Color(red:0.45,green:0.32,blue:0.76),Color(red:0.28,green:0.40,blue:0.79)]};return [Color(red:0.64,green:0.55,blue:0.98),Color(red:0.40,green:0.54,blue:0.99)]}
        if scheme == .light{return [Color(red:0.10,green:0.45,blue:0.72),Color(red:0.08,green:0.58,blue:0.43)]}
        return [Color(red:0.26,green:0.75,blue:0.96),Color(red:0.28,green:0.84,blue:0.69)]
    }
    var brand:String {
        let label=quota.label.lowercased()
        if label.contains("claude") || service=="claude"{return "claude"}
        if service.hasPrefix("codex") || label.contains("gpt"){return "openai"}
        if label.contains("gemini"){return "gemini"}
        if service.hasPrefix("antigravity") || service=="agy"{return "antigravity"}
        return ""
    }
    var title:String {let name=quota.label.components(separatedBy:" · ").first ?? quota.label;return name.isEmpty ? "Лимит":name}
    var period:String {
        let raw=quota.label.components(separatedBy:" · ").dropFirst().joined(separator:" · ").lowercased()
        if raw=="weekly" || raw=="7 days"{return "На неделю"}
        if raw=="daily" || raw=="1 day"{return "На день"}
        if raw=="five_hour" || raw=="5h"{return "На 5 часов"}
        return raw.isEmpty ? "Лимит аккаунта":raw
    }
    var statusColor:Color {expired ? (scheme == .dark ? .orange:Color(red:0.67,green:0.34,blue:0.02)):colors[0]}
    var status:String {
        if quota.disabled == true{return "Недоступно"}
        if expired{return "Обновить"}
        guard let value=remaining else{return amount.map{$0<=0 ? "Исчерпан":"Доступно"} ?? "Нет данных"}
        if value<=0{return "Исчерпан"}
        return value<=25 ? "Заканчивается":"Доступно"
    }
    var valueText:String {
        if let value=remaining{return value>0 && value<1 ? "<1":String(Int(value.rounded()))}
        if let value=amount{return value.formatted(.number.notation(.compactName).precision(.fractionLength(0...1)).locale(Locale(identifier:"ru_RU")))}
        return "—"
    }
    var resetText:String {
        guard let reset=quota.resetAt else{return "Сброс не указан"}
        let seconds=reset-now.timeIntervalSince1970
        if seconds<=0{return "Пора обновить данные"}
        let minutes=max(1,Int(ceil(seconds/60)))
        if minutes<60{return "Через \(minutes) мин"}
        if minutes<1440{return "Через \(minutes/60) ч \(minutes%60) мин"}
        return "Через \(minutes/1440) дн \((minutes%1440)/60) ч"
    }
    var body:some View {
        VStack(alignment:.leading,spacing:14){
            HStack(spacing:8){
                ZStack{RoundedRectangle(cornerRadius:8,style:.continuous).fill(Color.primary.opacity(0.045));if brand.isEmpty{Image(systemName:"chart.pie.fill").foregroundStyle(colors[0])}else{BrandImage(name:brand).frame(width:18,height:18)}}.frame(width:27,height:27)
                VStack(alignment:.leading,spacing:2){Text(title).font(.system(size:12,weight:.semibold)).lineLimit(1);Text(period).font(.system(size:9)).foregroundStyle(.secondary).lineLimit(1)}
                Spacer(minLength:3)
                HStack(spacing:4){Circle().fill(statusColor).frame(width:4,height:4);Text(status).font(.system(size:9,weight:.medium)).lineLimit(1)}.foregroundStyle(statusColor).padding(.horizontal,7).padding(.vertical,5).background((statusColor).opacity(0.09),in:Capsule())
            }
            HStack(alignment:.center){
                VStack(alignment:.leading,spacing:1){Text(quota.disabled == true ? "Лимит недоступен":"Осталось в запасе").font(.system(size:10)).foregroundStyle(.secondary);QuotaValue(value:valueText,percent:remaining != nil)}
                Spacer(minLength:10)
                QuotaRing(remaining:ringRemaining,colors:colors,disabled:quota.disabled == true)
            }.frame(height:76)
            HStack(spacing:5){Image(systemName:expired ? "arrow.clockwise":"clock").font(.system(size:9,weight:.medium));Text(resetText).font(.system(size:10,weight:.medium));Spacer(minLength:0);if let reset=quota.resetAt,!expired{Text(Date(timeIntervalSince1970:reset).formatted(date:.omitted,time:.shortened)).font(.system(size:9)).monospacedDigit().opacity(0.65)}}.foregroundStyle(expired ? statusColor:Color.secondary)
                .help(quota.resetAt.map{"Сброс: "+Date(timeIntervalSince1970:$0).formatted(date:.abbreviated,time:.shortened)} ?? "Клиент не указал время сброса")
        }.padding(15)
        .background(RoundedRectangle(cornerRadius:18,style:.continuous).fill(LinearGradient(colors:[Color.primary.opacity(scheme == .dark ? 0.045:0.018),colors[0].opacity(scheme == .dark ? 0.055:0.035)],startPoint:.topLeading,endPoint:.bottomTrailing)))
        .overlay(RoundedRectangle(cornerRadius:18,style:.continuous).strokeBorder(LinearGradient(colors:[Color.primary.opacity(scheme == .dark ? 0.12:0.07),colors[0].opacity(0.12),Color.primary.opacity(0.035)],startPoint:.topLeading,endPoint:.bottomTrailing),lineWidth:1))
        .accessibilityElement(children:.combine)
        .help(quota.label)
    }
}
struct QuotaDesignGallery:View {
    @Environment(\.dismiss) var dismiss
    let now=Date()
    var examples:[QuotaWindow] {
        if ProcessInfo.processInfo.environment["DAGAMI_UI_LIMITS_EDGE"]=="1" {return [
            QuotaWindow(id:"unknown",label:"Gemini · weekly",usedPercent:nil,remainingAmount:nil,resetAt:nil,disabled:false),
            QuotaWindow(id:"disabled",label:"Claude · weekly",usedPercent:nil,remainingAmount:nil,resetAt:nil,disabled:true),
            QuotaWindow(id:"fraction",label:"GPT · 5h",usedPercent:99.6,remainingAmount:nil,resetAt:now.addingTimeInterval(1800).timeIntervalSince1970,disabled:false),
            QuotaWindow(id:"stale",label:"Gemini Pro · daily",usedPercent:nil,remainingAmount:0,resetAt:now.addingTimeInterval(-3600).timeIntervalSince1970,disabled:false)
        ]}
        return [
        QuotaWindow(id:"gemini",label:"Gemini · 5h",usedPercent:28,remainingAmount:nil,resetAt:now.addingTimeInterval(5460).timeIntervalSince1970,disabled:false),
        QuotaWindow(id:"claude",label:"Claude · weekly",usedPercent:54,remainingAmount:nil,resetAt:now.addingTimeInterval(187200).timeIntervalSince1970,disabled:false),
        QuotaWindow(id:"gpt",label:"GPT · 5h",usedPercent:88,remainingAmount:nil,resetAt:now.addingTimeInterval(2400).timeIntervalSince1970,disabled:false),
        QuotaWindow(id:"empty",label:"Gemini Pro · daily",usedPercent:100,remainingAmount:nil,resetAt:now.addingTimeInterval(12600).timeIntervalSince1970,disabled:false)
    ]}
    var body:some View {
        VStack(alignment:.leading,spacing:18){
            HStack(alignment:.top){VStack(alignment:.leading,spacing:4){Text("Лимиты").font(.system(size:25,weight:.bold,design:.rounded));Text("Демонстрация оформления · значения для примера").font(.system(size:11)).foregroundStyle(.secondary)};Spacer();Button{dismiss()}label:{Image(systemName:"xmark.circle.fill").font(.system(size:20)).foregroundStyle(.secondary)}.buttonStyle(.plain)}
            LazyVGrid(columns:[GridItem(.flexible(),spacing:12),GridItem(.flexible())],spacing:12){ForEach(examples){quota in QuotaMetricCard(quota:quota,service:"",now:now)}}
            HStack(spacing:6){Image(systemName:"info.circle");Text("Полное кольцо — полный запас. Данные аккаунта не изменяются.")}.font(.system(size:10)).foregroundStyle(.secondary)
        }.padding(25).frame(width:660).background(Color(nsColor:.windowBackgroundColor))
    }
}
struct QuotaRows:View {
    var report:SessionTelemetry
    var service:String=""
    var body:some View {
        VStack(alignment:.leading,spacing:10){
            if let quotas=report.quotas,!quotas.isEmpty {
                TimelineView(.periodic(from:.now,by:60)){context in
                    LazyVGrid(columns:quotas.count==1 ? [GridItem(.flexible())]:[GridItem(.adaptive(minimum:235),spacing:10)],spacing:10){ForEach(quotas){quota in QuotaMetricCard(quota:quota,service:service,now:context.date)}}
                }
            }
            HStack(spacing:5){Image(systemName:"arrow.triangle.2.circlepath").font(.system(size:8));Text("Данные клиента").font(.system(size:9));Spacer();if let updated=report.updatedAt{Text("Обновлено "+Date(timeIntervalSince1970:updated).formatted(date:.omitted,time:.shortened)).font(.system(size:9)).monospacedDigit()}}.foregroundStyle(.secondary).help(report.source ?? "Лимиты предоставлены клиентом")
        }
    }
}
struct SessionInsights:View {
    @EnvironmentObject var model:Model
    var session:ManagedSession
    var app:String {session.app ?? session.id}
    var report:SessionTelemetry? {model.quotaReports[session.id] ?? session.telemetry}
    var body:some View {
        VStack(alignment:.leading,spacing:10){
            if let stats=session.telemetry {
                HStack(spacing:7){Circle().fill(stats.isWorking == true ? Color.green:(stats.isWorking == false ? Color.secondary:Color.orange)).frame(width:7,height:7);Text(stats.activityBadge).font(.system(size:12,weight:.semibold));Spacer();if let name=stats.model,!name.isEmpty{Text(name).font(.system(size:10)).foregroundStyle(.secondary).lineLimit(1)}}
                if stats.isWorking == true || (stats.state != "idle" && stats.isWorking != nil) {Text(stats.activity).font(.system(size:10)).foregroundStyle(.secondary)}
                if let context=stats.contextUsed {Text("Контекст разговора: \(Int(context))% — отдельно от квоты аккаунта").font(.system(size:10)).foregroundStyle(.secondary)}
                if let note=stats.note,!note.isEmpty{Text(note).font(.system(size:10)).foregroundStyle(.secondary)}
            } else {Text("Клиент не предоставил данные о текущем действии.").font(.system(size:10)).foregroundStyle(.secondary)}
            if let report=report,let quotas=report.quotas,!quotas.isEmpty {QuotaRows(report:report,service:app)}
            else {Text("Лимиты пока не предоставлены клиентом.").font(.system(size:10)).foregroundStyle(.secondary)}
            if let error=model.quotaErrors[session.id]{Text(error).font(.system(size:10)).foregroundStyle(.orange).textSelection(.enabled)}
            if let report=model.quotaReports[session.id],let note=report.note{Text(note).font(.system(size:10)).foregroundStyle(.secondary)}
            if ["codex","codex-gui","antigravity","antigravity-ide"].contains(app) {
                Button{model.run("sessionQuota",["session":session.id],refresh:false)}label:{Label("Обновить лимиты",systemImage:"arrow.clockwise")}.disabled(model.busy)
                if app.hasPrefix("antigravity") && !(model.state.desktopMonitoring ?? false) {Button("Подключить активность приложения"){model.run("desktopMonitoring",["enabled":true])}.disabled(model.busy)}
            } else if app=="agy" {Text("Родная панель квот: /usage в CLI.").font(.system(size:10)).foregroundStyle(.secondary)}
        }
    }
}
