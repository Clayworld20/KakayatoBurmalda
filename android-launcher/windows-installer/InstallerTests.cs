using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MiLiteInstaller;

static class InstallerTests {
    static int checks;
    static void Check(bool ok, string message) { if (!ok) throw new Exception(message); checks++; }
    static void Reject(Action action) { try { action(); } catch(ArgumentException) { checks++; return; } throw new Exception("Invalid input was accepted"); }
    static int Main(string[] args) {
        Console.OutputEncoding=Encoding.UTF8;
        if(args.Length>0) {
            if(args[0]=="flood") { Console.Write(new string('x',200000)); Console.Error.Write(new string('y',200000)); return 7; }
            if(args[0]=="wait") { Thread.Sleep(10000); return 0; }
        }
        try { Run().GetAwaiter().GetResult(); Console.WriteLine("PASS: "+checks+" checks"); return 0; }
        catch(Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
    static async Task Run() {
        Check(InstallerCore.Endpoint("192.168.1.50","5555")=="192.168.1.50:5555","Basic endpoint");
        Check(InstallerCore.Endpoint(" 10.0.0.5 ","1")=="10.0.0.5:1","Trim endpoint");
        Check(InstallerCore.Endpoint("10.0.0.5","65535").EndsWith(":65535"),"Max port");
        foreach(string ip in new[]{"", "192.168.0.999", "127.1", "tv.local", "192.168.1.2 & whoami", "192.168.1.2:5555", "::1", "1.2.3.4\""}) Reject(()=>InstallerCore.Endpoint(ip,"5555"));
        foreach(string port in new[]{"", "0", "65536", "-1", "5555 & echo", "5.5", " 5555", "2147483648"}) Reject(()=>InstallerCore.Endpoint("192.168.1.2",port));
        Check(InstallerCore.PairCode(" 012345 ")=="012345","Leading-zero pair code");
        foreach(string code in new[]{"12345","1234567","12345&","abcdef","１２３４５６"}) Reject(()=>InstallerCore.PairCode(code));
        Check(InstallerCore.DeviceProblem(0,"device\r\n")==null,"Authorized TV");
        Check(InstallerCore.DeviceProblem(1,"error: device unauthorized.").Contains("Подтвердите"),"Authorization prompt");
        Check(InstallerCore.DeviceProblem(1,"offline").Contains("не отвечает"),"Offline TV");
        Check(InstallerCore.DeviceProblem(0,"not a device")!=null,"Don't assume success");
        Check(InstallerCore.Installed(0,"Performing Streamed Install\r\nSuccess\r\n"),"Confirmed installation");
        Check(!InstallerCore.Installed(1,"Success"),"Preserve nonzero exit");
        Check(!InstallerCore.Installed(0,"Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]"),"Failed install");
        Check(!InstallerCore.Installed(0,"Not Success"),"Don't match success substring");
        Check(InstallerCore.InstallProblem("INSTALL_FAILED_UPDATE_INCOMPATIBLE").Contains("подписью"),"Signing mismatch explanation");
        Check(InstallerCore.InstallProblem("INSTALL_FAILED_INSUFFICIENT_STORAGE").Contains("места"),"Storage explanation");
        Check(InstallerCore.Quote("a b")=="\"a b\"","Spaces in paths");
        Check(InstallerCore.Quote("a\"b")=="\"a\\\"b\"","Embedded quote");
        Check(InstallerCore.Quote("C:\\folder\\")=="\"C:\\folder\\\\\"","Trailing slash");
        string temp=Path.GetTempFileName();
        try { File.WriteAllText(temp,"abc",new UTF8Encoding(false)); Check(InstallerCore.Sha256(temp)=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad","Bundle checksum"); }
        finally { File.Delete(temp); }
        string assembly=Assembly.GetExecutingAssembly().Location;
        bool managedDll=assembly.EndsWith(".dll",StringComparison.OrdinalIgnoreCase);
        string executable=managedDll?Process.GetCurrentProcess().MainModule.FileName:assembly;
        string prefix=managedDll?InstallerCore.Quote(assembly)+" ":"";
        CommandResult flood=await CommandRunner.Run(executable,prefix+"flood",15000);
        Check(flood.ExitCode==7,"Preserve subprocess exit status");
        Check(flood.Output.Length>=400000,"Drain stdout and stderr without deadlock");
        bool timedOut=false;
        try { await CommandRunner.Run(executable,prefix+"wait",200); } catch(TimeoutException) { timedOut=true; }
        Check(timedOut,"Kill stalled client and report timeout");
    }
}
