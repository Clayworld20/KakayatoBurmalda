using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;

namespace MiLiteInstaller {
    public static class InstallerCore {
        public static string Endpoint(string address, string port) {
            IPAddress ip;
            int number;
            if (!IPAddress.TryParse(address.Trim(), out ip) || ip.AddressFamily != AddressFamily.InterNetwork || address.Trim().Split('.').Length != 4)
                throw new ArgumentException("Введите IPv4-адрес телевизора, например 192.168.1.50.");
            if (!int.TryParse(port, NumberStyles.None, CultureInfo.InvariantCulture, out number) || number < 1 || number > 65535)
                throw new ArgumentException("Порт должен быть числом от 1 до 65535.");
            return ip.ToString() + ":" + number.ToString(CultureInfo.InvariantCulture);
        }
        public static string PairCode(string value) {
            string code = value.Trim();
            if (code.Length != 6 || code.Any(c => c < '0' || c > '9')) throw new ArgumentException("Введите шестизначный код сопряжения с экрана ТВ.");
            return code;
        }
        public static string Quote(string arg) {
            // Windows CommandLineToArgvW quoting; never invoke cmd.exe or a shell.
            StringBuilder output = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in arg) {
                if (c == '\\') { slashes++; continue; }
                if (c == '"') output.Append('\\', slashes * 2 + 1);
                else output.Append('\\', slashes);
                slashes = 0; output.Append(c);
            }
            output.Append('\\', slashes * 2); output.Append('"'); return output.ToString();
        }
        public static string DeviceProblem(int exitCode, string output) {
            string status = output.Trim();
            if (exitCode == 0 && status == "device") return null;
            if (status.IndexOf("unauthorized", StringComparison.OrdinalIgnoreCase) >= 0)
                return "Подтвердите разрешение отладки на экране телевизора и нажмите кнопку ещё раз.";
            if (status.IndexOf("offline", StringComparison.OrdinalIgnoreCase) >= 0)
                return "Телевизор не отвечает. Проверьте подключение к сети и отладку на ТВ, затем повторите.";
            return "Не удалось подключиться к ТВ. Проверьте IP, порт, общую сеть Wi-Fi и включённую отладку по сети. При сопряжении используйте порт подключения, а не порт кода.";
        }
        public static bool Installed(int exitCode, string output) {
            return exitCode == 0 && output.Split(new[] {'\r','\n'}, StringSplitOptions.RemoveEmptyEntries).Any(line => line.Trim() == "Success");
        }
        public static string InstallProblem(string output) {
            if (output.Contains("INSTALL_FAILED_UPDATE_INCOMPATIBLE")) return "Уже установлена версия с другой подписью. Удалите прежний MiLite TV через настройки ТВ (избранное будет потеряно), затем повторите установку.";
            if (output.Contains("INSTALL_FAILED_VERSION_DOWNGRADE")) return "На ТВ установлена более новая версия MiLite TV. Обновление остановлено.";
            if (output.Contains("INSTALL_FAILED_INSUFFICIENT_STORAGE")) return "На телевизоре не хватает свободного места. Освободите место и повторите.";
            if (output.Contains("INSTALL_FAILED_OLDER_SDK")) return "Эта версия Android слишком старая для MiLite TV. Нужен Android 6.0 или новее.";
            return "Android не подтвердил установку. Проверьте запросы на экране ТВ. Подробности доступны в поле ниже.";
        }
        public static string Sha256(string file) {
            using (SHA256 sha = SHA256.Create()) using (FileStream stream = File.OpenRead(file))
                return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
    }
    public sealed class CommandResult {
        public int ExitCode;
        public string Output;
    }
    public static class CommandRunner {
        public static Task<CommandResult> Run(string file, string arguments, int timeoutMs) {
            return Task.Run(async delegate {
                using (Process process = new Process()) {
                    process.StartInfo = new ProcessStartInfo(file, arguments) {
                        UseShellExecute = false, CreateNoWindow = true,
                        RedirectStandardOutput = true, RedirectStandardError = true,
                        StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
                    };
                    process.Start();
                    Task<string> stdout = process.StandardOutput.ReadToEndAsync();
                    Task<string> stderr = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(timeoutMs)) {
                        try { process.Kill(); } catch (InvalidOperationException) { }
                        // ADB's shared server is deliberately left running.
                        throw new TimeoutException("Телевизор не ответил вовремя. Проверьте экран ТВ и повторите попытку.");
                    }
                    return new CommandResult { ExitCode = process.ExitCode, Output = (await stdout) + "\n" + (await stderr) };
                }
            });
        }
    }
}
