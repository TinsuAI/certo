Option Explicit
Sub xuatCtu()
Dim fullPath As String
Dim folderPath As String ' folder chua file can in
Dim fileName As String ' tên file
Dim sheetName As String ' tên sheet trong file
Dim pageRange As String ' vùng cân in
Dim wbTarget As Workbook ' File c?n in
Dim wsTarget As Worksheet   ' sheet can in
Dim i As Long, lastRow As Long
Dim wsSave As Worksheet, wsDM As Worksheet
Dim pageNum As Long
Dim pages() As String
Dim p As Variant
Dim answer As Integer


Set wsSave = ThisWorkbook.Sheets("Save")
Set wsDM = ThisWorkbook.Sheets("DM")
lastRow = wsSave.Cells(wsSave.Rows.Count, "A").End(xlUp).row


Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

' Đuong dân  chua file cân xuât
Dim actualFileName As String
folderPath = wsSave.Range("X1")


    
answer = MsgBox("Do you want to proceed that ?", vbYesNo) ' hien thi yes/no
Select Case answer
        Case vbYes
         'dat bien tao wb moi
            Dim wb As Workbook, newWb As Workbook
            Dim newSheet As Worksheet
            Dim newSheetName As String
            Dim sFileName As String ' dua con tro vao file name trong o J8
            Dim xPath As String ' tao duong dan
            Dim lastPasteRow As Long
            xPath = Application.ActiveWorkbook.Path
                               
            'copy các trang cân in vao file excel moi
            sFileName = "docs" ' dat ten file cho wb
            Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,dat tên là filename
            Set newWb = wb ' gán  wb moi
                                           
             ' T?o sheet duy nh?t d? ch?a t?t c? trang du?c copy
  
            
            For i = 2 To lastRow
            On Error GoTo ContinueLoop ' B?t l?i riêng t?ng ṿng l?p
                If wsSave.Range("R" & i) = wsDM.Range("K6") Then ' nêu sô tkx = ô K6
                    If wsSave.Range("C" & i) <> "" Then ' nêu ô mă LH # rông => có sô tk
                        fileName = LCase("ToKhaiHQ7N_QDTQ_" & Trim(wsSave.Range("A" & i))) ' tên file cân xuât
                        actualFileName = Dir(folderPath & fileName & ".*") ' t́m tên file bao gôm ca phân mo rông cua file
                        pageRange = "1," & (wsSave.Range("D" & i) + 2) ' trang cân xuât ctu
                        If fileName <> "" And pageRange <> "" Then ' bây lôi
                            If actualFileName <> "" Then ' bay loi neu file trong folder ko ṭn tai
                                fullPath = folderPath & actualFileName ' duong dan folder + tên file
                                Set wbTarget = Workbooks.Open(fullPath) 't́m dên folder có chua sô tk và mo file excel lên
                                Set wsTarget = wbTarget.Sheets(1) ' t́m dên sheetname dâu tiên
                                ' ân ḍng 20
                                wsTarget.Rows("20").Hidden = True
                                
                                ' Tao sheet moi voi tên A_D
                                newSheetName = CStr(wsSave.Range("A" & i).Value) & "_" & CStr(wsSave.Range("D" & i).Value) ' dat tên sheet = stk + _ḍng hàng
            
                                Set newSheet = newWb.Sheets.Add(After:=newWb.Sheets(newWb.Sheets.Count)) ' chèn thêm sheet moi vào wb moi
                                newSheet.Name = newSheetName ' dat tên sheet moi = stk&stt ḍng hàng
                                lastPasteRow = 1 ' reset môi lân tao sheet moi

                                ' Dán t?t c? vào 1 sheet duy nh?t
                                Call CopyPages1(wsTarget, newSheet, pageRange, lastPasteRow)
                                'Call CopyPages2(wsTarget, newSheet, pageRange, lastPasteRow)
                                'Call CopyPages3(wsTarget, newSheet, pageRange, lastPasteRow)
            
                                wbTarget.Close SaveChanges:=False
                                Set wsTarget = Nothing
                            Else
                                MsgBox "Không t́m thây file: " & fullPath, vbExclamation
                                
                            End If
                        End If
                    End If
                End If
ContinueLoop:         ' tiep tuc ṿng lap khi có lôi
            Next i
            
        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.DisplayAlerts = False
        newWb.Sheets("docs").Delete ' xoá sheet dau tien di
        Application.DisplayAlerts = True
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel
        newWb.Activate ' quay tro ve wb moi khoi tao
        

        ' gôp các sheet lai thành 1 file pdf
          Call xuatCtuPdf(newWb)
            
        Case vbNo
            MsgBox ("OK!")
    End Select
    
lbFinally: ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
    
End Sub

Sub CopyPages1(wsSource As Worksheet, destSheet As Worksheet, pageRange As String, ByRef lastPasteRow As Long)
    Dim pageStarts() As Long
    Dim i As Long, j As Long, p As Variant
    Dim pages() As String
    Dim totalPages As Long
    Dim rngStart As Long, rngEnd As Long
    Dim pasteRow As Long
    Dim srcRange As Range, destCell As Range
    Dim r As Long, c As Long
    Dim lastRowSource As Integer
    
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

      
        lastRowSource = wsSource.Cells(wsSource.Rows.Count, "D").End(xlUp).row ' t́m ḍng cuôi theo côt D
        
        wsSource.Activate
        
        'Ngat các trang con lai theo IMP
        For i = 2 To lastRowSource
            If wsSource.Cells(i, "C").Text = "<IMP>" Then ' gân giông <IMP>
                wsSource.HPageBreaks.Add Before:=wsSource.Rows(i)
            End If
       Next i
        totalPages = wsSource.HPageBreaks.Count + 1 'dem tông sô trang da ngat

        ReDim pageStarts(1 To totalPages) ' tao mang luu dong bat dau cua tung trang
        pageStarts(1) = 1 ' Trang dâu luôn bat dâu tu ḍng 1
        
        't́m trang bat dau trong các trang dă ngat
        For i = 1 To wsSource.HPageBreaks.Count ' cho bien i chay tu 1 den sô trang da ngat
            pageStarts(i + 1) = wsSource.HPageBreaks(i).Location.row 'ḍng bat dau cua trang da ngat = vi trí cua hàng
        Next i
        
        pages = Split(Replace(pageRange, " ", ""), ",") ' tách só trang tu pagerange
        
        For Each p In pages
            If IsNumeric(p) Then ' kiêm tra nêu p là sô
                i = CLng(p) ' dôi p thành sô nguyên i
                If i < 1 Or i > totalPages Then GoTo SkipPage ' nêu i ngoài tông so trang
                    rngStart = pageStarts(i) 'pageStarts(i) chua ḍng bat dau cua trang thu i (duoc tính san truoc dó).
                If i < totalPages Then
                    rngEnd = pageStarts(i + 1) - 1 ' Neu không phai trang cuoi, ḍ̣ng kêt thúc là ngay truoc ḍng bat dau cua trang tiêp theo.
                Else
                    rngEnd = lastRowSource ' Nêu là trang cuôi, ḍng kêt thúc là lastRow.
                End If
    
            If rngStart > rngEnd Then GoTo SkipPage ' Neu du liêu rông (vùng không hop lê), bo qua.
            Set srcRange = wsSource.Range("A" & rngStart & ":AH" & rngEnd) 'Xác dinh vùng can copy tu A dên AH trong khoang tu ḍng rngStart dên rngEnd

            ' Xác dinh ḍng cân dán
            If lastPasteRow < 1 Then lastPasteRow = 1
                pasteRow = lastPasteRow
                Set destCell = destSheet.Range("A" & pasteRow)
    
                ' Copy du liêu + d?nh d?ng
                On Error Resume Next
                srcRange.Copy Destination:=destCell
                On Error GoTo 0
                Application.CutCopyMode = False
                 
                
                'destSheet.ResetAllPageBreaks ' Xoá tât ca ngat trang cu truoc dó
                destSheet.HPageBreaks.Add Before:=destSheet.Rows(76) ' Ngat trang sau ḍng 75 (tuc là ngat tai ḍng 76)
                

                ' Copy chiêu cao ḍng
                For r = rngStart To rngEnd
                    destSheet.Rows(pasteRow + (r - rngStart)).RowHeight = wsSource.Rows(r).RowHeight
                Next r
    
                ' Copy dô rông côt
                For c = 1 To srcRange.Columns.Count
                    destSheet.Columns(c).ColumnWidth = wsSource.Columns(c).ColumnWidth
                Next c
    
                ' Câp nhât ḍng cuôi
                lastPasteRow = pasteRow + srcRange.Rows.Count
            End If
SkipPage:
        Next p
        

    ' Copy PageSetup
    With destSheet.PageSetup
        .Orientation = wsSource.PageSetup.Orientation
        .PaperSize = wsSource.PageSetup.PaperSize
        .Zoom = wsSource.PageSetup.Zoom
        .FitToPagesWide = wsSource.PageSetup.FitToPagesWide
        .FitToPagesTall = wsSource.PageSetup.FitToPagesTall
        .LeftMargin = wsSource.PageSetup.LeftMargin
        .RightMargin = wsSource.PageSetup.RightMargin
        .TopMargin = wsSource.PageSetup.TopMargin
        .BottomMargin = wsSource.PageSetup.BottomMargin
        .HeaderMargin = wsSource.PageSetup.HeaderMargin
        .FooterMargin = wsSource.PageSetup.FooterMargin
        .CenterHorizontally = wsSource.PageSetup.CenterHorizontally
        .CenterVertically = wsSource.PageSetup.CenterVertically
    End With

    ' Hi?n th? ch? d? xem Page Break Preview
    destSheet.Activate
    ActiveWindow.View = xlPageBreakPreview
        

lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
End Sub
  


Sub CopyPages2(wsSource As Worksheet, destSheet As Worksheet, pageRange As String, ByRef lastPasteRow As Long)
    Dim breaks As HPageBreaks
    Dim pageStarts() As Long
    Dim i As Long, p As Variant
    Dim pages() As String
    Dim totalPages As Long
    Dim rngStart As Long, rngEnd As Long
    Dim pasteRow As Long
    Dim srcRange As Range, destCell As Range
    Dim brk As HPageBreak
    Dim r As Long, c As Long

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra
        
   
    Dim lastRowSource As Integer
    Dim stepRow As Integer
        
        'Thiêt lâp PageSetup dê không ép tât ca vào 1 trang ( tránh lôi)
        With wsSource.PageSetup
            .Zoom = False
            .FitToPagesWide = 1
            .FitToPagesTall = False
        End With
        
        wsSource.ResetAllPageBreaks ' Xoá tât ca ngat trang cu truoc dó
        lastRowSource = wsSource.Cells(wsSource.Rows.Count, "D").End(xlUp).row ' t́m ḍng cu?i theo c?t D
        
        ' Ngat trang sau ḍng 75 (tuc là ngat tai ḍng 76)
        wsSource.HPageBreaks.Add Before:=wsSource.Rows(76)
        ' Ngat trang sau ḍng 138 (tuc là ngat tai ḍng 139)
        wsSource.HPageBreaks.Add Before:=wsSource.Rows(139)
        ' Ngat các trang c̣n lai, bat dau tu ḍng 192 (139 + 53)
        stepRow = 53
        For i = 192 To lastRowSource Step stepRow
            If i <= lastRowSource Then wsSource.HPageBreaks.Add Before:=wsSource.Rows(i) ' them if bây lôi
        Next i
        
        totalPages = wsSource.HPageBreaks.Count + 1 'dem tông sô trang da ngat
        ReDim pageStarts(1 To totalPages) ' tao mang luu dong bat dau cua tung trang
        pageStarts(1) = 1 ' Trang dâu luôn bat dâu tu ḍng 1
        For i = 1 To wsSource.HPageBreaks.Count ' cho bien i chay tu 1 den sô trang da ngat
            pageStarts(i + 1) = wsSource.HPageBreaks(i).Location.row
        Next i
        
        pages = Split(Replace(pageRange, " ", ""), ",") ' tách só trang tu pagerange
        
        For Each p In pages
            If IsNumeric(p) Then ' kiêm tra nêu p là sô
                i = CLng(p) ' dôi p thành sô nguyên i
                If i < 1 Or i > totalPages Then GoTo SkipPage ' nêu i ngoài tông so trang
                    rngStart = pageStarts(i) 'pageStarts(i) chua ḍng bat dau cua trang thu i (duoc tính san truoc dó).
                If i < totalPages Then
                    rngEnd = pageStarts(i + 1) - 1 ' Neu không phai trang cuoi, ḍ̣ng kêt thúc là ngay truoc ḍng bat dau cua trang tiêp theo.
                Else
                    rngEnd = lastRowSource ' Nêu là trang cuôi, ḍng kêt thúc là lastRow.
                End If
    
            If rngStart > rngEnd Then GoTo SkipPage ' Neu du liêu rông (vùng không hop lê), bo qua.
            Set srcRange = wsSource.Range("A" & rngStart & ":AH" & rngEnd) 'Xác dinh vùng can copy tu A dên AH trong khoang tu ḍng rngStart dên rngEnd

            ' Xác dinh ḍng cân dán
            If lastPasteRow < 1 Then lastPasteRow = 1
                pasteRow = lastPasteRow
                Set destCell = destSheet.Range("A" & pasteRow)
    
                ' Copy du liêu + d?nh d?ng
                On Error Resume Next
                srcRange.Copy Destination:=destCell
                On Error GoTo 0
                Application.CutCopyMode = False
                 
                
                destSheet.ResetAllPageBreaks ' Xoá tât ca ngat trang cu truoc dó
                destSheet.HPageBreaks.Add Before:=destSheet.Rows(76) ' Ngat trang sau ḍng 75 (tuc là ngat tai ḍng 76)

                ' Copy chiêu cao ḍng
                For r = rngStart To rngEnd
                    destSheet.Rows(pasteRow + (r - rngStart)).RowHeight = wsSource.Rows(r).RowHeight
                Next r
    
                ' Copy dô rông côt
                For c = 1 To srcRange.Columns.Count
                    destSheet.Columns(c).ColumnWidth = wsSource.Columns(c).ColumnWidth
                Next c
    
                ' Câp nhât ḍng cuôi
                lastPasteRow = pasteRow + srcRange.Rows.Count
            End If
SkipPage:
        Next p
        

    ' Copy PageSetup
    With destSheet.PageSetup
        .Orientation = wsSource.PageSetup.Orientation
        .PaperSize = wsSource.PageSetup.PaperSize
        .Zoom = wsSource.PageSetup.Zoom
        .FitToPagesWide = wsSource.PageSetup.FitToPagesWide
        .FitToPagesTall = wsSource.PageSetup.FitToPagesTall
        .LeftMargin = wsSource.PageSetup.LeftMargin
        .RightMargin = wsSource.PageSetup.RightMargin
        .TopMargin = wsSource.PageSetup.TopMargin
        .BottomMargin = wsSource.PageSetup.BottomMargin
        .HeaderMargin = wsSource.PageSetup.HeaderMargin
        .FooterMargin = wsSource.PageSetup.FooterMargin
        .CenterHorizontally = wsSource.PageSetup.CenterHorizontally
        .CenterVertically = wsSource.PageSetup.CenterVertically
    End With

    ' Hi?n th? ch? d? xem Page Break Preview
    destSheet.Activate
    'ActiveWindow.View = xlPageBreakPreview
        

lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
End Sub


Sub CopyPages3(wsSource As Worksheet, destSheet As Worksheet, pageRange As String, ByRef lastPasteRow As Long)
    Dim pageStarts() As Long
    Dim i As Long, j As Long, p As Variant
    Dim pages() As String
    Dim totalPages As Long
    Dim rngStart As Long, rngEnd As Long
    Dim pasteRow As Long
    Dim srcRange As Range, destCell As Range
    Dim r As Long, c As Long
    Dim lastRowSource As Integer
 
    
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

        Dim arrSource As Variant
        lastRowSource = wsSource.Cells(wsSource.Rows.Count, "D").End(xlUp).row ' t́m ḍng cuôi theo côt D
        
        'khoi tao mang
        arrSource = wsSource.Range("A1:AH" & lastRowSource).Value
        
        wsSource.Activate
        
        'Ngat các trang con lai theo IMP
        Dim breakCount As Integer
        Dim firstIMP As Boolean
           breakCount = 0
           firstIMP = False
            For i = 1 To UBound(arrSource, 1)
                If Trim(UCase(arrSource(i, 3))) = "<IMP>" Then
                    breakCount = breakCount + 1
                    If i = 1 Then firstIMP = True
                End If
            Next i
            
            If firstIMP Then
                totalPages = breakCount
            Else
                totalPages = breakCount + 1
            End If

    
        ReDim pageStarts(1 To totalPages) ' tao mang luu ḍng bat dau cua tung trang
        pageStarts(1) = 1 ' Trang dâu luôn bat dâu tu ḍng 1
        
        r = 2 ' r là sô trang
        For i = 2 To UBound(arrSource, 1) 'chay tu ḍng 2, v́ ḍng 1 dă có IMP rôi
            If arrSource(i, 3) = "<IMP>" Then 'Nêu gap <IMP> ? côt 3 dây là vi trí bat dâu trang moi.
                If r <= totalPages Then ' nêu r <= 2 trang nham Đam bao  không ghi quá sô phân tu mang pageStarts.
                    pageStarts(r) = i ' trang thu r bat dau bang ḍng i
                    r = r + 1 'tang sô trang lên
                End If
            End If
        Next i
        
        pages = Split(Replace(pageRange, " ", ""), ",") ' tách só trang tu pagerange
        
        '--- Xác d?nh ḍng dán ban d?u ---
        If lastPasteRow < 1 Then lastPasteRow = 1
        pasteRow = lastPasteRow
        
        '--- Duyet tung trang trong pageRange ---
        Dim arrPage As Variant
        For Each p In pages
        Dim pageNum As Long
            If IsNumeric(p) Then ' kiêm tra nêu p là sô
                pageNum = CLng(p) ' dôi p thành sô nguyên i
                If pageNum >= 1 And pageNum <= totalPages Then '
                    rngStart = pageStarts(pageNum) 'pageStarts(i) chua ḍng bat dau cua trang thu i (duoc tính san truoc dó).
                    If pageNum < totalPages Then
                        rngEnd = pageStarts(pageNum + 1) - 1 ' Neu không phai trang cuoi, ḍ̣ng kêt thúc là ngay truoc ḍng bat dau cua trang tiêp theo.
                    Else
                        rngEnd = UBound(arrSource, 1) ' Nêu là trang cuôi, ḍng kêt thúc là lastRow.
                    End If
                    
                    Set srcRange = wsSource.Range("A" & rngStart & ":AH" & rngEnd) 'Xác dinh vùng can copy tu A dên AH trong khoang tu ḍng rngStart dên rngEnd
                    If rngStart <= rngEnd Then
                    '--- T?o m?ng con 2 chi?u ---
                        Dim rowCount As Long, colCount As Long
                            rowCount = rngEnd - rngStart + 1
                            colCount = UBound(arrSource, 2)
                            
                            '--- T?o m?ng con 2D ---
                            ReDim arrPage(1 To rowCount, 1 To colCount)
                            For r = 1 To rowCount
                                For c = 1 To colCount
                                    arrPage(r, c) = arrSource(rngStart + r - 1, c)
                                Next c
                            Next r
                            
                            '--- Dán d? li?u ---
                            destSheet.Cells(pasteRow, 1).Resize(rowCount, colCount).Value = arrPage
                    
                        '--- Copy chi?u cao ḍng ---
                        For r = rngStart To rngEnd
                            destSheet.Rows(pasteRow + (r - rngStart)).RowHeight = wsSource.Rows(r).RowHeight
                        Next r
                    
                        '--- Copy d? r?ng c?t ---
                        For c = 1 To colCount
                            destSheet.Columns(c).ColumnWidth = wsSource.Columns(c).ColumnWidth
                        Next c
                    
                        '--- C?p nh?t v? trí dán ti?p theo ---
                        pasteRow = pasteRow + rowCount + 1
                    End If
                End If
            End If
        Next p
        
           '--- Luu lai vi trí paste cuôi ---
            lastPasteRow = pasteRow

    ' Copy PageSetup
    With destSheet.PageSetup
        .Orientation = wsSource.PageSetup.Orientation
        .PaperSize = wsSource.PageSetup.PaperSize
        .Zoom = wsSource.PageSetup.Zoom
        .FitToPagesWide = wsSource.PageSetup.FitToPagesWide
        .FitToPagesTall = wsSource.PageSetup.FitToPagesTall
        .LeftMargin = wsSource.PageSetup.LeftMargin
        .RightMargin = wsSource.PageSetup.RightMargin
        .TopMargin = wsSource.PageSetup.TopMargin
        .BottomMargin = wsSource.PageSetup.BottomMargin
        .HeaderMargin = wsSource.PageSetup.HeaderMargin
        .FooterMargin = wsSource.PageSetup.FooterMargin
        .CenterHorizontally = wsSource.PageSetup.CenterHorizontally
        .CenterVertically = wsSource.PageSetup.CenterVertically
    End With

    ' Hi?n th? ch? d? xem Page Break Preview
    destSheet.Activate
    ActiveWindow.View = xlPageBreakPreview
        

lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
End Sub


Sub xuatCtuPdf(wb As Workbook)
Dim xFileName As String, xPath As String
Dim arrSheets() As Variant
Dim ws As Worksheet
Dim i As Integer

  Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra

xPath = Application.ActiveWorkbook.Path
xFileName = "PDF"

   Dim lastRow As Integer
   
     ' Chon rơ tung sheet (tránh loi sheet hidden, chua active)
    ReDim arrSheets(1 To wb.Sheets.Count)
    For i = 1 To wb.Sheets.Count
        Set ws = wb.Sheets(i)
        ' Bo qua sheet ân hoac không muon in
        If ws.Visible = xlSheetVisible Then
            ' Bat buoc activate de Excel câp nhât PageSetup( dánh thúc worksheet)
            ws.Activate
            lastRow = ws.Cells(ws.Rows.Count, "D").End(xlUp).row
            ws.Rows("1:" & lastRow).RowHeight = 10    ' Đ?t chi?u cao t?t c? các ḍng v? 10
            DoEvents
            arrSheets(i) = ws.Name
        End If
    Next i
    
    ' Xuât PDF dúng thiêt lâp cua tung sheet
    wb.Sheets(arrSheets).Select

    ' Cài d?t kh? gi?y Letter và Fit
    With ws.PageSetup
        .PaperSize = xlPaperLetter
        .Orientation = xlPortrait  ' ho?c xlLandscape n?u b?n mu?n ngang
        .Zoom = False
        .FitToPagesWide = 1
        .FitToPagesTall = False    ' Ho?c d?t là 1 n?u mu?n gi?i h?n chi?u cao
        .TopMargin = Application.InchesToPoints(0.3)
        .BottomMargin = Application.InchesToPoints(0.3)
        .LeftMargin = Application.InchesToPoints(0.2)
        .RightMargin = Application.InchesToPoints(0.2)
    End With

 
 ' Xuat toàn bô các sheet thành 1 PDF
    ActiveSheet.ExportAsFixedFormat _
        Type:=xlTypePDF, _
        fileName:=xPath & "\" & xFileName & ".pdf", _
        Quality:=xlQualityMinimum, _
        IncludeDocProperties:=True, _
        IgnorePrintAreas:=False, _
        OpenAfterPublish:=True
        
  
lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
        
        
End Sub



Function CreateNewWb(sWbName As String) As Workbook
 Dim oldWb As Workbook
 
   Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False 'ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra



 Set oldWb = ActiveWorkbook ' tra ve man hinh workbook cu
 Set CreateNewWb = Workbooks.Add ' tao moi workbook
 'CreateNewWb.SaveAs sWbName ' luu ten file theo filename
     ' Đat tên Sheet
    On Error Resume Next
    CreateNewWb.Sheets(1).Name = Right(sWbName, 10)
    On Error GoTo 0
 
 oldWb.Activate
 
lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
 End Function
 
 Function GetWb(sWbName As String, wb As Workbook) As Boolean ' kieu true or false
' neu GetWb = true thi WB tro vao workbook co ten o tham so sWbName
' neu GetWb = false thi chua co file co ten
    Dim i As Long ' kiem tra xem nhung wb dang open
    
    Application.ScreenUpdating = False ' ngung update man hinh
    Application.DisplayAlerts = False 'ko canh bao
    Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra
    
    
    sWbName = UCase(sWbName)
        For i = 1 To Workbooks.Count
            If UCase(Workbooks(i).Name) = sWbName Then
                GetWb = True
                Set wb = Workbooks(i)
                Exit Function
            End If
         Next i
         
         
lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
         
End Function
