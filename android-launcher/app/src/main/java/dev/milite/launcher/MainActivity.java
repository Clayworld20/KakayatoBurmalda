package dev.milite.launcher;

import android.app.*;
import android.os.*;
import android.content.*;
import android.content.pm.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.*;
import android.net.*;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

/** Local-only TV home: no feeds, analytics, network requests or background services. */
public class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService loader = Executors.newSingleThreadExecutor();
    private final List<Entry> apps = new ArrayList<>();
    private LinearLayout content;
    private TextView clock, vpn;
    private android.content.SharedPreferences prefs;
    private ConnectivityManager connectivity;
    private boolean observing;
    private boolean loaded;
    private static final int TEXT = Color.rgb(245,247,255);
    private static final int MUTED = Color.rgb(164,176,198);
    private final Runnable tick = new Runnable() {
        public void run() {
            if (clock != null) clock.setText(new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date()));
            handler.postDelayed(this, 30000);
        }
    };
    private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(Network network) { handler.post(() -> updateVpn()); }
        @Override public void onLost(Network network) { handler.post(() -> updateVpn()); }
        @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) { handler.post(() -> updateVpn()); }
    };
    static class Entry {
        String label, pkg;
        Intent launch;
        Drawable icon;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("home", MODE_PRIVATE);
        connectivity = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(42), dp(26), dp(42), dp(16));
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{0xff182337,0xff10131c,0xff151321}));
        setContentView(root);
        LinearLayout header = new LinearLayout(this);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = text("MiLite TV", 26, TEXT);
        title.setTypeface(null, Typeface.BOLD);
        header.addView(title, new LinearLayout.LayoutParams(0,dp(54),1));
        clock = text("",24,TEXT); header.addView(clock);
        root.addView(header);
        root.addView(text("Ваши приложения. Ничего лишнего.",14,MUTED));
        LinearLayout actions = new LinearLayout(this);
        actions.setPadding(0,dp(22),0,dp(16));
        vpn = action("VPN · проверка", () -> openVpn());
        actions.addView(vpn, actionParams());
        actions.addView(action("Избранное", () -> chooseFavorites()), actionParams());
        actions.addView(action("Настройки ТВ", () -> launch(new Intent(Settings.ACTION_SETTINGS))), actionParams());
        actions.addView(action("Домашний экран", () -> showHomeHelp()), actionParams());
        root.addView(actions);
        ScrollView scroll = new ScrollView(this);
        scroll.setClipToPadding(false);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(content);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        root.addView(text("ОК — открыть    ·    Удерживать ОК — добавить в избранное",12,MUTED));
        vpn.requestFocus();
    }
    private LinearLayout.LayoutParams actionParams() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, dp(48), 1);
        p.setMargins(0,0,dp(12),0); return p;
    }
    @Override public void onResume() {
        super.onResume();
        handler.removeCallbacks(tick); tick.run(); updateVpn();
        try {
            connectivity.registerNetworkCallback(new NetworkRequest.Builder().removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN).build(),networkCallback);
            observing = true;
        } catch (RuntimeException ignored) { }
        refreshApps();
    }
    @Override public void onPause() {
        handler.removeCallbacks(tick);
        if (observing) { try { connectivity.unregisterNetworkCallback(networkCallback); } catch (RuntimeException ignored) {} observing = false; }
        super.onPause();
    }
    @Override public void onDestroy() { loader.shutdownNow(); handler.removeCallbacksAndMessages(null); super.onDestroy(); }
    private void refreshApps() {
        loader.execute(() -> {
            PackageManager pm = getPackageManager();
            Map<String,Entry> found = new LinkedHashMap<>();
            for (String category : new String[]{Intent.CATEGORY_LEANBACK_LAUNCHER,Intent.CATEGORY_LAUNCHER}) {
                Intent query = new Intent(Intent.ACTION_MAIN).addCategory(category);
                for (ResolveInfo info : pm.queryIntentActivities(query,0)) {
                    String pkg = info.activityInfo.packageName;
                    if (pkg.equals(getPackageName()) || found.containsKey(pkg)) continue;
                    Entry e = new Entry(); e.pkg = pkg; e.label = info.loadLabel(pm).toString();
                    e.launch = new Intent(Intent.ACTION_MAIN).addCategory(category)
                        .setComponent(new ComponentName(pkg,info.activityInfo.name))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
                    e.icon = info.loadIcon(pm); found.put(pkg,e);
                }
            }
            List<Entry> result = new ArrayList<>(found.values());
            Collections.sort(result, (a,b) -> a.label.compareToIgnoreCase(b.label));
            handler.post(() -> {
                if (isFinishing() || isDestroyed()) return;
                boolean same = loaded && apps.size() == result.size();
                for (int i=0; same && i<apps.size(); i++) same = apps.get(i).pkg.equals(result.get(i).pkg) && apps.get(i).label.equals(result.get(i).label);
                if (!same) { apps.clear(); apps.addAll(result); loaded = true; render(); }
            });
        });
    }
    private Set<String> favorites() { return new HashSet<>(prefs.getStringSet("favorites",Collections.emptySet())); }
    private void render() {
        content.removeAllViews();
        Set<String> selected = favorites();
        List<Entry> favorites = new ArrayList<>();
        for (Entry e:apps) if (selected.contains(e.pkg)) favorites.add(e);
        if (!favorites.isEmpty()) section("Избранное",favorites,true);
        section("Все приложения",apps,false);
        if (apps.isEmpty()) content.addView(text("Приложения не найдены. Откройте настройки телевизора.",16,MUTED));
    }
    private void section(String title,List<Entry> entries,boolean favorite) {
        TextView heading = text(title,19,TEXT); heading.setPadding(0,dp(12),0,dp(12)); content.addView(heading);
        LinearLayout row = null;
        for (int i=0;i<entries.size();i++) {
            if (i%5 == 0) { row = new LinearLayout(this); row.setPadding(dp(5),dp(5),dp(5),dp(5)); row.setClipChildren(false); content.addView(row); }
            Entry e = entries.get(i);
            LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setGravity(Gravity.CENTER);
            card.setPadding(dp(8),dp(14),dp(8),dp(10));
            ImageView icon = new ImageView(this); icon.setImageDrawable(e.icon); icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
            card.addView(icon,new LinearLayout.LayoutParams(dp(48),dp(48)));
            TextView label = text(e.label,13,TEXT); label.setGravity(Gravity.CENTER); label.setSingleLine(); label.setEllipsize(android.text.TextUtils.TruncateAt.END); label.setPadding(0,dp(12),0,0);
            card.addView(label,new LinearLayout.LayoutParams(-1,-2));
            focusable(card,0xff242d40);
            card.setContentDescription(e.label);
            card.setOnClickListener(v -> launch(e.launch));
            card.setOnLongClickListener(v -> {
                Set<String> f = favorites(); boolean added = !f.remove(e.pkg); if (added) f.add(e.pkg);
                prefs.edit().putStringSet("favorites",f).apply();
                toast(added ? "Добавлено в избранное" : "Удалено из избранного");
                // Re-render after the key event; focus stays on the same app when possible.
                handler.post(() -> { render(); focusPackage(e.pkg); }); return true;
            });
            card.setTag(e.pkg);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0,dp(118),1); lp.setMargins(0,0,dp(12),dp(12)); row.addView(card,lp);
        }
        if (row != null) for (int n=entries.size()%5; n>0 && n<5;n++) row.addView(new View(this),new LinearLayout.LayoutParams(0,1,1));
    }
    private void focusPackage(String pkg) { View v = content.findViewWithTag(pkg); if (v != null) v.requestFocus(); }
    private void chooseFavorites() {
        if (!loaded || apps.isEmpty()) { toast("Дождитесь загрузки приложений"); return; }
        String[] labels = new String[apps.size()]; boolean[] checked = new boolean[apps.size()]; Set<String> chosen = favorites();
        for (int i=0;i<apps.size();i++) { labels[i]=apps.get(i).label; checked[i]=chosen.contains(apps.get(i).pkg); }
        new AlertDialog.Builder(this).setTitle("Избранные приложения").setMultiChoiceItems(labels,checked,(d,i,on) -> {
            if(on) chosen.add(apps.get(i).pkg); else chosen.remove(apps.get(i).pkg);
        }).setPositiveButton("Сохранить",(d,w) -> { prefs.edit().putStringSet("favorites",chosen).apply(); render(); }).setNegativeButton("Отмена",null).show();
    }
    private void openVpn() {
        String preferred = prefs.getString("vpnPackage", "");
        for (Entry e:apps) if (e.pkg.equals(preferred)) { launch(e.launch); return; }
        for (Entry e:apps) {
            String identity = (e.label+e.pkg).toLowerCase(Locale.ROOT).replace(" ","").replace("-","");
            if (identity.contains("v2raytun")) { launch(e.launch); return; }
        }
        if (apps.isEmpty()) { toast("Дождитесь загрузки приложений"); return; }
        String[] labels = new String[apps.size()]; for(int i=0;i<apps.size();i++) labels[i]=apps.get(i).label;
        new AlertDialog.Builder(this).setTitle("Выберите VPN-приложение").setItems(labels,(d,i)-> {
            prefs.edit().putString("vpnPackage",apps.get(i).pkg).apply(); launch(apps.get(i).launch);
        }).setNegativeButton("Отмена",null).show();
    }
    private void updateVpn() {
        if (vpn==null) return;
        try {
            boolean active = false;
            for (Network n:connectivity.getAllNetworks()) {
                NetworkCapabilities c = connectivity.getNetworkCapabilities(n);
                if(c!=null && c.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) { active = true; break; }
            }
            vpn.setText(active ? "VPN · подключён" : "VPN · не подключён");
            vpn.setContentDescription(vpn.getText()+". Открыть VPN-приложение. Статус по данным Android, провайдер не определяется.");
        } catch (RuntimeException ex) { vpn.setText(R.string.vpn_unknown); }
    }
    private void showHomeHelp() {
        new AlertDialog.Builder(this).setTitle("Домашний экран").setMessage("Нажмите Home на пульте. Если Android предложит выбор, выберите MiLite TV и «Всегда». На некоторых прошивках Xiaomi смена домашнего экрана ограничена. Штатный лаунчер удалять не нужно.")
            .setPositiveButton("Настройки",(d,w)->launch(new Intent(Settings.ACTION_HOME_SETTINGS))).setNegativeButton("Понятно",null).show();
    }
    private void launch(Intent intent) {
        try { startActivity(intent); } catch (RuntimeException ex) { toast("Не удалось открыть. Проверьте приложение в настройках ТВ."); }
    }
    private TextView text(String s,int size,int color) { TextView t=new TextView(this); t.setText(s); t.setTextSize(size); t.setTextColor(color); t.setGravity(Gravity.CENTER_VERTICAL); return t; }
    private TextView action(String label,Runnable run) { TextView t=text(label,14,TEXT); t.setGravity(Gravity.CENTER); t.setPadding(dp(8),0,dp(8),0); focusable(t,0xff263146); t.setOnClickListener(v->run.run()); return t; }
    private void focusable(View v,int color) {
        v.setFocusable(true); v.setClickable(true);
        StateListDrawable state = new StateListDrawable();
        GradientDrawable focused = new GradientDrawable(); focused.setColor(0xff3b5274); focused.setCornerRadius(dp(14)); focused.setStroke(dp(2),0xffc6dfff);
        GradientDrawable normal = new GradientDrawable(); normal.setColor(color); normal.setCornerRadius(dp(14));
        state.addState(new int[]{android.R.attr.state_focused},focused); state.addState(new int[]{android.R.attr.state_pressed},focused); state.addState(new int[]{},normal); v.setBackground(state);
        v.setOnFocusChangeListener((view,has)->view.animate().scaleX(has?1.035f:1f).scaleY(has?1.035f:1f).setDuration(110).start());
    }
    private int dp(int n) { return Math.round(n*getResources().getDisplayMetrics().density); }
    private void toast(String s) { Toast.makeText(this,s,Toast.LENGTH_SHORT).show(); }
    @Override public void onBackPressed() { vpn.requestFocus(); }
}
