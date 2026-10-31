using System;
using System.Drawing;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace MiLiteInstaller {
    public sealed class InstallerForm : Form {
        readonly TextBox address = new TextBox();
        readonly TextBox port = new TextBox();
        readonly TextBox pairPort = new TextBox();
        readonly TextBox pairCode = new TextBox();
        readonly TextBox details = new TextBox();
        readonly Label status = new Label();
        readonly Button install = new Button();
        readonly Button pair = new Button();
        readonly Button settings = new Button();
        readonly Button open = new Button();
        readonly CheckBox advanced = new CheckBox();
        readonly GroupBox pairing = new GroupBox();
        readonly string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        bool busy;
        public InstallerForm() {
            Text = "Установка MiLite TV";
            ClientSize = new Size(660, 650); MinimumSize = new Size(680, 690);
            StartPosition = FormStartPosition.CenterScreen; Font = new Font("Segoe UI", 10);
            BackColor = Color.FromArgb(245,247,251); AutoScaleMode = AutoScaleMode.Dpi;
            AddLabel("MiLite TV", 22, 18, 610, 40, 22, true);
            AddLabel("Установите лёгкий главный экран на телевизор Xiaomi", 24, 65, 610, 28, 11, false);
            AddLabel("1. Подключите ПК и телевизор к одной сети.\n2. На ТВ включите отладку по сети в параметрах разработчика.\n3. Введите IP из настроек сети ТВ и нажмите кнопку установки.\n   Если ТВ спросит разрешение отладки — подтвердите его пультом.",24,104,610,100,10,false);
            AddLabel("IP телевизора",24,217,370,24,10,false);
            AddLabel("Порт подключения",432,217,195,24,10,false);
            address.SetBounds(24,244,385,30); address.AccessibleName="IP телевизора";
            port.SetBounds(432,244,192,30); port.Text="5555"; port.AccessibleName="Порт подключения";
            Controls.Add(address); Controls.Add(port);
            advanced.Text="На ТВ есть «Беспроводная отладка» с кодом сопряжения";
            advanced.SetBounds(24,282,610,28); Controls.Add(advanced);
            pairing.Text="Сопряжение (для новых версий Android)"; pairing.SetBounds(24,318,600,88); pairing.Enabled=false;
            pairPort.SetBounds(15,38,130,28); pairPort.AccessibleName="Порт сопряжения";
            pairCode.SetBounds(157,38,130,28); pairCode.AccessibleName="Код сопряжения"; pairCode.UseSystemPasswordChar=true; pairCode.MaxLength=6;
            Label portHint=new Label { Text="Порт сопряжения", Left=15, Top=18, Width=135 };
            Label codeHint=new Label { Text="Код с экрана ТВ", Left=157, Top=18, Width=140 };
            pair.Text="Сопрячь"; pair.SetBounds(310,35,265,32);
            pairing.Controls.AddRange(new Control[]{portHint,codeHint,pairPort,pairCode,pair}); Controls.Add(pairing);
            advanced.CheckedChanged += delegate { if(!busy) pairing.Enabled=advanced.Checked; };
            install.Text="Установить и открыть"; install.SetBounds(24,420,600,46);
            install.BackColor=Color.FromArgb(43,96,180); install.ForeColor=Color.White; install.FlatStyle=FlatStyle.Flat;
            Controls.Add(install); AcceptButton=install;
            open.Text="Открыть MiLite TV"; open.SetBounds(24,477,289,34);
            settings.Text="Настройки телевизора"; settings.SetBounds(325,477,299,34);
            Controls.Add(open); Controls.Add(settings);
            status.Text="Готово к подключению"; status.SetBounds(24,522,600,44); Controls.Add(status);
            details.SetBounds(24,570,600,54); details.Multiline=true; details.ReadOnly=true; details.ScrollBars=ScrollBars.Vertical;
            details.AccessibleName="Подробности операции"; Controls.Add(details);
            install.Click += async delegate { await Execute(Install); };
            pair.Click += async delegate { await Execute(Pair); };
            open.Click += async delegate { await Execute(async delegate {
                string endpoint=await Connect(); await Open(endpoint); status.Text="MiLite TV открыт на телевизоре.";
            }); };
            settings.Click += async delegate { await Execute(async delegate {
                string endpoint=await Connect(); CommandResult r=await Adb("-s "+endpoint+" shell am start -a android.settings.SETTINGS",30000);
                CheckLaunch(r); status.Text="Настройки открыты на ТВ. Выберите домашний экран в меню приложений.";
            }); };
            FormClosing += delegate(object sender,FormClosingEventArgs e) {
                if(busy) { e.Cancel=true; MessageBox.Show(this,"Дождитесь завершения операции.",Text); }
            };
        }
        void AddLabel(string text,int x,int y,int width,int height,float size,bool bold) {
            Label label=new Label { Text=text, Left=x,Top=y,Width=width,Height=height,Font=new Font("Segoe UI",size,bold?FontStyle.Bold:FontStyle.Regular) }; Controls.Add(label);
        }
        void ValidateBundle() {
            // Hashes are generated during packaging, never taken from mutable sidecar files.
            for(int i=0;i<BundleIntegrity.Files.Length;i++) {
                string path=Path.Combine(baseDir,BundleIntegrity.Files[i]);
                if(!File.Exists(path) || InstallerCore.Sha256(path)!=BundleIntegrity.Hashes[i])
                    throw new IOException("Файлы комплекта отсутствуют или повреждены. Полностью распакуйте исходный ZIP в новую папку и откройте установщик оттуда.");
            }
        }
        async Task Execute(Func<Task> operation) {
            if(busy) return;
            busy=true; install.Enabled=open.Enabled=settings.Enabled=advanced.Enabled=pairing.Enabled=address.Enabled=port.Enabled=false;
            details.Clear();
            try { ValidateBundle(); await operation(); }
            catch(Exception error) { status.Text=error.Message; MessageBox.Show(this,error.Message,"MiLite TV",MessageBoxButtons.OK,MessageBoxIcon.Information); }
            finally {
                busy=false; install.Enabled=open.Enabled=settings.Enabled=advanced.Enabled=address.Enabled=port.Enabled=true;
                pairing.Enabled=advanced.Checked;
            }
        }
        Task<CommandResult> Adb(string args,int timeout) { return CommandRunner.Run(Path.Combine(baseDir,"platform-tools","adb.exe"),args,timeout); }
        async Task<string> Connect() {
            string endpoint=InstallerCore.Endpoint(address.Text,port.Text);
            status.Text="Подключаемся к телевизору. Подтвердите запрос на экране ТВ, если он появится…";
            await Adb("connect "+endpoint,20000);
            CommandResult state=await Adb("-s "+endpoint+" get-state",15000);
            string problem=InstallerCore.DeviceProblem(state.ExitCode,state.Output);
            if(problem!=null) throw new InvalidOperationException(problem);
            return endpoint;
        }
        async Task Pair() {
            string endpoint=InstallerCore.Endpoint(address.Text,pairPort.Text);
            string code=InstallerCore.PairCode(pairCode.Text);
            status.Text="Сопряжение с телевизором…";
            try {
                CommandResult result=await Adb("pair "+endpoint+" "+code,30000);
                if(result.ExitCode!=0 || result.Output.IndexOf("Successfully paired",StringComparison.OrdinalIgnoreCase)<0)
                    throw new InvalidOperationException("Сопряжение не завершено. Откройте новый код на ТВ, проверьте порт сопряжения и повторите.");
                status.Text="Сопряжение выполнено. Укажите порт подключения с главного экрана беспроводной отладки и нажмите «Установить и открыть».";
            } finally { pairCode.Clear(); }
        }
        async Task Install() {
            string endpoint=await Connect();
            status.Text="Устанавливаем MiLite TV. Обычно это занимает несколько секунд…";
            CommandResult result=await Adb("-s "+endpoint+" install -r "+InstallerCore.Quote(Path.Combine(baseDir,"MiLite-TV.apk")),180000);
            details.Text=result.Output;
            if(!InstallerCore.Installed(result.ExitCode,result.Output)) throw new InvalidOperationException(InstallerCore.InstallProblem(result.Output));
            await Open(endpoint);
            status.Text="Установлено! Проверьте экран ТВ. Для выбора домашнего экрана нажмите Home. Штатный лаунчер сохранён.";
        }
        async Task Open(string endpoint) {
            CommandResult result=await Adb("-s "+endpoint+" shell am start -n dev.milite.launcher/.MainActivity",30000);
            CheckLaunch(result);
        }
        void CheckLaunch(CommandResult result) {
            if(result.ExitCode!=0 || result.Output.IndexOf("Error",StringComparison.OrdinalIgnoreCase)>=0 || result.Output.Contains("Exception")) {
                details.Text=result.Output;
                throw new InvalidOperationException("Не удалось открыть экран на ТВ. Подробности показаны внизу окна.");
            }
        }
    }
    static class Program {
        [STAThread] static void Main() {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }
}
