# যমুনা নদীর আকৃতি পরিবর্তনের নিউরাল পূর্বাভাস: পঞ্চাশ বছরের ল্যান্ডস্যাট আর্কাইভ থেকে চরবাসীদের বাস্তুচ্যুতি সতর্কতা ব্যবস্থা নির্মাণ

**মো. সাজ্জাদ সিদ্দিকী**

বাংলা একাডেমির তিনমাস মেয়াদি গবেষণা-প্রবন্ধ বৃত্তি (তৃতীয় পর্যায়), ক্রমিক ১০

---

## সারসংক্ষেপ

যমুনা নদীর তীরভাঙনে বাংলাদেশে প্রতি বছর হাজার হাজার পরিবার ভিটেমাটি হারায়, অথচ
ভাঙনের পূর্বাভাস এখনো মূলত বার্ষিক এবং কয়েকটি নির্দিষ্ট স্থানে সীমাবদ্ধ। এই
গবেষণার উদ্দেশ্য তিনটি: বায়ান্ন বছরের ল্যান্ডস্যাট উপাত্ত থেকে যমুনার মাসভিত্তিক
তীররেখার নথি পুনর্গঠন; সেই নথির উপর একটি নিউরাল মডেল প্রশিক্ষণ দিয়ে তিন মাস আগাম
তীররেখার অবস্থান অনুমান; এবং সেই অনুমানকে ইউনিয়ন পরিষদ পর্যায়ে ঝুঁকিপূর্ণ
পরিবারের সংখ্যায় রূপান্তর। উপাদান ল্যান্ডস্যাট ১–৯ অভিযানের ১৯৭২–২০২৪ সালের দৃশ্য,
যা থেকে সংশোধিত স্বাভাবিকীকৃত পার্থক্য জলসূচক (MNDWI)—এবং SWIR ব্যান্ডবিহীন MSS
পর্বের জন্য NDWI—দিয়ে মাসিক জলমুখোশ নির্ণয় করা হয়েছে ১২০ মিটার বিভেদনে, ইউটিএম
৪৫উ (EPSG:32645) মেট্রিক স্থানাঙ্কে, যাতে স্থানচ্যুতি ত্রুটি মিটারে প্রকাশ করা
যায়। পূর্বাভাসের জন্য টাইমসফরমার (TimeSformer) স্থাপত্যের শ্রেণিবিন্যাস স্তরের
বদলে পিক্সেলভিত্তিক সিএনএন ডিকোডার বসানো হয়েছে; ক্ষতি-অপেক্ষক দ্বিমুখী
ক্রস-এনট্রপি ও ০.৩ গুণ সোবেল গ্রেডিয়েন্ট ক্ষতির যোগফল; তুলনামূলক মডেল
কনভএলএসটিএম ও স্থিতাবস্থা। দুটি পর্যবেক্ষণ উল্লেখযোগ্য। প্রথমত, সংগ্রহশালা
ধারাবাহিক নয়—সাতটি বছরে একটিও ব্যবহারযোগ্য দৃশ্য নেই, এবং পিক্সেল-মাসের মাত্র
৫৩.৬ শতাংশ প্রত্যক্ষ পর্যবেক্ষণ। দ্বিতীয়ত, কেবল পিক্সেলভিত্তিক ক্ষতি ব্যবহার করলে
তীররেখা ঝাপসা করা মডেলের পক্ষে পরিমাপযোগ্যভাবে সস্তা হয়ে ওঠে; গ্রেডিয়েন্ট পদ সেই
প্রণোদনা দূর করে। গবেষণার তাৎপর্য—একটি পূর্বাভাস তখনই কার্যকর, যখন তা বলতে পারে
কোন ইউনিয়নের কতটি পরিবার ঝুঁকিতে।

**মুখশব্দ:** নদীভাঙন, যমুনা, চরাঞ্চল, ল্যান্ডস্যাট দূর-অনুধাবন, নিউরাল পূর্বাভাস, বাস্তুচ্যুতি-সতর্কতা

---

## Abstract

Riverbank erosion along the Jamuna displaces thousands of Bangladeshi
households every year, yet operational prediction remains annual and confined
to a few designated sites. This study reconstructs a monthly record of the
Jamuna shoreline from fifty-two years of Landsat imagery, trains a neural model
on it to forecast shoreline position three months ahead, and translates that
forecast into a count of at-risk households at union parishad level. Monthly
water masks are derived from Landsat 1–9 (1972–2024) using MNDWI, and NDWI for
the Multispectral Scanner era, which carries no shortwave infrared band. All
rasters are held at 120 m in EPSG:32645, a metric projection, so displacement
error can be reported in metres. The forecaster replaces the TimeSformer
classification head with a pixel-wise convolutional decoder, trained with
binary cross-entropy plus 0.3 times a Sobel gradient loss; ConvLSTM and
persistence are baselines under an identical interface. Two findings stand out.
The archive is not continuous: seven years carry no usable scene at all, and
only 53.6 per cent of pixel-months are directly observed. And a pixel-wise loss
alone rewards hedging — blurring the bank is measurably cheaper for the model
than committing to a position — which the gradient term corrects. The wider
argument is that an erosion forecast becomes useful only where it can name how
many households in which union stand to lose their land.

**Keywords:** riverbank erosion, Jamuna, chars, Landsat remote sensing, neural forecasting, displacement early warning
