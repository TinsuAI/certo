Option Explicit
Sub index_Match3()
Dim lookupRange, vlookupRange, lookupRangeXK1, lookupRangeXK2, r As Range 'tao bien r chay
Dim i, j, k, l, stt, hang, cot, lastRow, lastRow2, lastRow3, lastRow4, lastRow5 As Long
Dim result1, result2, result3, result4, result5 As String
Dim findStartNumL, findStartNumN As Integer
With ThisWorkbook.Sheets("LVC")
lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("DM").Cells(.Rows.Count, "F").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:Q" & lastRow2)


'cài dat thoi han su dung
Dim hanchot As Date
    hanchot = DateSerial(2025, 12, 31)
        If Now() > hanchot Then
            MsgBox "Qua han su dung " & CStr(hanchot)
            ThisWorkbook.Close SaveChanges:=False
        End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path

    sFileName = "LVC" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb

' dien du lieu header
lastRow5 = .Cells(.Rows.Count, "W").End(xlUp).row
lastRow4 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "U").End(xlUp).row
Set lookupRangeXK1 = ThisWorkbook.Sheets("XK").Range("B11:BB" & lastRow4)
Set lookupRangeXK2 = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow4)
        .Range("P6") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 10, 0) ' ty gia
        .Range("O8") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 17, 0) ' incoterm
        .Range("P10") = Application.WorksheetFunction.SumIf(ThisWorkbook.Sheets("XK").Range("B11:B" & lastRow4), _
        .Range("Q9"), ThisWorkbook.Sheets("XK").Range("AE11:AE" & lastRow4))  ' tong tri gia
    For l = 16 To lastRow5 ' ****** cot moc vong lap de xuat file excel
    ThisWorkbook.Sheets("LVC").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & l) ' mă SP vao ô P7
        .Range("K7") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 7, 0) ' ten sp
        .Range("K8") = Left(Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 6, 0), 6) ' HS code sp
        .Range("P8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 9, 0) ' don gia
        .Range("L9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 12, 0) ' dvt
        .Range("K9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("P9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("K10") = .Range("P8") * .Range("P9") ' tri gia exw
        .Range("I10") = "Tri giá " & .Range("O8") '  incoterm
        .Range("L10") = "USD"
        .Range("L11") = "USD"
        .Range("Q10") = .Range("V" & l) ' dat ten file
        .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P103") ' tri gia FOB


' tim so luong dong ma dinh muc sp
    Set vlookupRange = ThisWorkbook.Sheets("DM").Range("B7:I" & lastRow3)
    .Range("P5") = Application.WorksheetFunction.CountIf(ThisWorkbook.Sheets("DM") _
    .Range("A7:A" & lastRow3), .Range("P7")) ' t́m sl dm
    .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
   
    
'chay vong lap dien gia tri
 lastRow = .Cells(.Rows.Count, "T").End(xlUp).row
    stt = 0
     For i = 16 To lastRow
         stt = stt + 1
        .Range("A" & i) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
        .Range("E" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 8, 0) ' lay dinh muc
        .Range("P" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 5, 0) ' lây mă nvl
        .Range("F" & i) = .Range("E" & i) * .Range("P9") ' tinh sl
        .Range("Q" & i) = .Range("Q9") & .Range("P" & i) ' tao cot phu
     Next
        
    For i = 16 To lastRow
    hang = Excel.WorksheetFunction.Match(.Cells(i, 17), ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2), 0)
       For j = 2 To 4
            cot = Excel.WorksheetFunction.Match(.Cells(15, j), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, j) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' dung ham index& match de lay data
       Next
            .Range("C" & i) = Left(.Range("C" & i), 6) ' lay 6 kư tu là hs code
            ' lay xuat xu
            cot = Excel.WorksheetFunction.Match(.Cells(15, 10), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 10) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            ' lay ty gia
            cot = Excel.WorksheetFunction.Match(.Cells(15, 18), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 18) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
             ' lay loai hinh
            cot = Excel.WorksheetFunction.Match(.Cells(15, 19), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 19) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            
        ' tinh tri gia trong nuoc & ngoai nuoc
        cot = Excel.WorksheetFunction.Match(.Cells(15, 7), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
        If .Range("S" & i) = "" Or .Range("S" & i) = "E15" Then ' ma lh de trong => mua trong nuoc
            .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia trong nuoc
            .Range("H" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia trong nuoc
        Else: .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia ngoai nuoc
        .Range("I" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia ngoai nuoc
        End If
           
    Next

lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
' gán két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    'lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).Row
    For k = 16 To lastRow
        For Each r In ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2)
            If r = .Cells(k, 17) Then
                 result1 = result1 & ";" & r.Offset(0, -22) ' lay stk dua vào 1 o excel
                .Range("K" & k) = Right(result1, Len(result1) - 1) ' bo dau cham phay o dau di
                 result2 = "'" & result2 & " " & r.Offset(0, -21) ' lay ngay tk dua vào 1 o excel, dau "'" dung sua loi ngay thang
                .Range("T" & k) = Right(result2, Len(result2) - 1) ' bo dau cham + phay o dau di
                '.Range("L" & k).NumberFormat = "mm/dd/yyyy" ' dinh dang ngay thang nam
                 result3 = result3 & ";" & r.Offset(0, -19) ' lay dong hang tk dua vào 1 o excel
                .Range("O" & k) = Right(result3, Len(result3) - 1) ' bo dau cham phai o dau di
                If .Range("S" & k) = "" Then
                     result4 = result4 & ";" & r.Offset(0, -9) ' lay so CO  dua vào 1 o excel
                    .Range("M" & k) = Right(result4, Len(result4) - 1) & "; Ty gia " & .Cells(k, 18).Value ' bo dau cham phai o dau di
                     result5 = "'" & result5 & " " & r.Offset(0, -8) ' lay ngay CO  dua vào 1 o excel, dau "'" dung sua loi ngay thang
                    .Range("U" & k) = Right(result5, Len(result5) - 1) ' bo dau cham phay o dau di
                Else: .Range("N" & k) = ""
                End If
            End If
         Next
         
         'remove khoang trang o dau
          findStartNumL = Application.WorksheetFunction.Find(" ", .Range("T" & k))
         .Range("L" & k) = Application.WorksheetFunction.Replace(.Range("T" & k), findStartNumL, 1, "") 'remove khoang trang o dau
         
         'remove khoang trang o dau
         If .Range("U" & k) <> "" Then
            findStartNumN = Application.WorksheetFunction.Find(" ", .Range("U" & k))
            .Range("N" & k) = Application.WorksheetFunction.Replace(.Range("U" & k), findStartNumN, 1, "") 'remove khoang trang o dau
         End If
 
         If Left(.Range("N" & k), 1) = ";" Then
            .Range("N" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
          If Left(.Range("M" & k), 1) = ";" Then
            .Range("M" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
         
' tra két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    Next
     .Range("T16:U" & lastRow) = "" ' xoa cot phu di
     .Range("Q16:Q" & lastRow) = "" ' xoa cot phu di
 
' an hàng rong  khong chua du lieu
    For i = 16 To 85
        If .Range("A" & i) = "" Then
            Worksheets("LVC").Rows(i).Hidden = True
        End If
    Next
 ' an cot du thua di
        .Range("O1:Y1").EntireColumn.Hidden = True
    
' tinh toan gia tri footer
    .Range("H1588") = Application.WorksheetFunction.Sum(.Range("H16:H1585")) ' tong trong nuoc
    .Range("I1588") = Application.WorksheetFunction.Sum(.Range("I16:I1585")) ' tong nuoc ngoai
    ' tong II chi phi nhan cong truc tiep
        .Range("I1590") = .Range("P1590") * .Range("K10") 'luong thuong
        .Range("I1591") = .Range("P1591") * .Range("K10") ' phuc loi y te
        .Range("I1593") = .Range("I1590") + .Range("I1591")
    ' tong III chi phi phan bo truc tiep
        .Range("I1595") = .Range("P1595") * .Range("K10") 'thue nhà xuong
        .Range("I1596") = .Range("P1596") * .Range("K10") 'khau hao
        .Range("I1597") = .Range("P1597") * .Range("K10") 'khau hao
        .Range("I1599") = .Range("I1595") + .Range("I1596") + .Range("I1597")
        
    ' tong IV chi phi xuat xuong
         .Range("I1600") = .Range("H1588") + .Range("I1588") + .Range("I1593") + .Range("I1599")

        If .Range("O8") = "EXW" Or .Range("O8") = "FCR" Then ' neu tk khai giá EXW
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            .Range("I1602") = .Range("K10") ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1604") = .Range("K11") ' tong VIII giá FOB
            
        ElseIf .Range("O8") = "FOB" Then ' neu tk khai giá FOB
            .Range("K11") = .Range("K10") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            .Range("I1604") = .Range("K11") ' tong VIII giá FOB
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1602") = .Range("I1604") - .Range("I1603")  ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
                
        Else ' truong hop nhóm C & D nhu CFR,CIF,CPT,DAP,DDU,DDP
        Dim freight As Long
            freight = (.Range("K10") / .Range("P10")) * .Range("P1604") ' cuoc biên
            .Range("I1604") = .Range("K10") - freight ' tong VIII giá FOB
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1602") = .Range("I1604") - .Range("I1603") ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
            .Range("K11") = .Range("I1604") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            
        End If

      ' Tinh LVC
         .Range("J1606") = Round(.Range("I1604"), 2) & "   - " ' 'Gia FOB
         .Range("J1609") = Round(.Range("I1604"), 2) 'Gia FOB
         .Range("C1586") = Round(Application.WorksheetFunction.SumIf(.Range("J16:J1585"), _
         "Vi" & ChrW(7879) & "t Nam", .Range("H16:H1585")), 2)
         'tim gia nl ko có xx chrwgo tieng viet co dau,Ctr + G mo cua so immediate => gơ tieng viet vao o selection
          .Range("K1606") = .Range("I1588") + .Range("H1588") - .Range("C1586")
          .Range("C1587") = .Range("K1606")
          .Range("M1607") = Round((.Range("J1609") - .Range("K1606")) / .Range("J1609") * 100, 2) & " %" ' tinh LVC
         
'copy LVC tu wb goc sang wb moi khoi tao

        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            ' copy paste value
            Range("A1:AA1623").Copy
            Range("A1:AA1623").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = .Range("Q10") ' dat ten sheet vua moi past
            
            ' tao file PDF ****
            With ActiveSheet.PageSetup
                ' Can trang gi?ng Print Preview
                .Orientation = xlLandscape ' ho?c xlLandscape tùy b?n
                .PaperSize = xlPaperA4
                .FitToPagesWide = 1
                .FitToPagesTall = 1
                ' L? chu?n (có th? tùy ch?nh)
                .TopMargin = Application.InchesToPoints(0.1)
                .BottomMargin = Application.InchesToPoints(0.1)
                .LeftMargin = Application.InchesToPoints(0.1)
                .RightMargin = Application.InchesToPoints(0.1)
            End With
            ' ? L?nh xu?t PDF gi?ng h?t Print Preview
                 ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, _
                IgnorePrintAreas:=False, _
                fileName:=xPath & "\" & ActiveSheet.Name
                     
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh ' tao sheet moi tren wb moi
    
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A16:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
       
    Next ' ****** cot moc vong lap de xuat file excel

        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel

lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub


Sub index_MatchCTH3()
Dim lookupRange, vlookupRange, lookupRangeXK1, lookupRangeXK2, r As Range 'tao bien r chay
Dim i, j, k, l, stt, hang, cot, lastRow, lastRow2, lastRow3, lastRow4, lastRow5 As Long
Dim result1, result2, result3, result4, result5 As String
Dim findStartNumL, findStartNumN As Integer
With ThisWorkbook.Sheets("CTH")
lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("DM").Cells(.Rows.Count, "F").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:Q" & lastRow2)


'cài dat thoi han su dung
Dim hanchot As Date
    hanchot = DateSerial(2025, 12, 31)
        If Now() > hanchot Then
            MsgBox "Qua han su dung " & CStr(hanchot)
            ThisWorkbook.Close SaveChanges:=False
        End If

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel


'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path

    sFileName = "CTH" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        

' dien du lieu header
lastRow5 = .Cells(.Rows.Count, "W").End(xlUp).row
lastRow4 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "U").End(xlUp).row
Set lookupRangeXK1 = ThisWorkbook.Sheets("XK").Range("B11:BB" & lastRow4)
Set lookupRangeXK2 = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow4)
        .Range("P6") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 10, 0) ' ty gia
        .Range("O8") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 17, 0) ' incoterm
        .Range("P10") = Application.WorksheetFunction.SumIf(ThisWorkbook.Sheets("XK").Range("B11:B" & lastRow4), _
        .Range("Q9"), ThisWorkbook.Sheets("XK").Range("AE11:AE" & lastRow4))  ' tong tri gia
        .Range("L10") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 11, 0) ' USD/VND
        .Range("L11") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 11, 0) ' USD/VND
    For l = 16 To lastRow5 ' ****** cot moc vong lap de xuat file excel
    ThisWorkbook.Sheets("CTH").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & l) ' mă SP vao ô P7
        .Range("K7") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 7, 0) ' ten sp
        .Range("K8") = Left(Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 6, 0), 6) ' HS code sp
        .Range("P8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 9, 0) ' don gia
        .Range("L9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 12, 0) ' dvt
        .Range("K9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("P9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("K10") = .Range("P8") * .Range("P9") ' tri gia exw
        .Range("Q10") = .Range("V" & l) ' dat ten file
        .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB


' tim so luong dong ma dinh muc sp
    Set vlookupRange = ThisWorkbook.Sheets("DM").Range("B7:I" & lastRow3)
    .Range("P5") = Application.WorksheetFunction.CountIf(ThisWorkbook.Sheets("DM") _
    .Range("A7:A" & lastRow3), .Range("P7")) ' t́m sl dm
    .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
   
    
'chay vong lap dien gia tri
 lastRow = .Cells(.Rows.Count, "T").End(xlUp).row
    stt = 0
     For i = 16 To lastRow
         stt = stt + 1
        .Range("A" & i) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
        .Range("E" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 8, 0) ' lay dinh muc
        .Range("P" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 5, 0) ' lây mă nvl
        .Range("F" & i) = .Range("E" & i) * .Range("P9") ' tinh sl
        .Range("Q" & i) = .Range("Q9") & .Range("P" & i) ' tao cot phu
     Next
        
    For i = 16 To lastRow
    hang = Excel.WorksheetFunction.Match(.Cells(i, 17), ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2), 0)
       For j = 2 To 4
            cot = Excel.WorksheetFunction.Match(.Cells(15, j), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, j) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' dung ham index& match de lay data
       Next
            .Range("C" & i) = Left(.Range("C" & i), 6) ' lay 6 kư tu là hs code
            ' lay xuat xu
            cot = Excel.WorksheetFunction.Match(.Cells(15, 10), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 10) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            ' lay ty gia
            cot = Excel.WorksheetFunction.Match(.Cells(15, 18), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 18) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
             ' lay loai hinh
            cot = Excel.WorksheetFunction.Match(.Cells(15, 19), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 19) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            
        ' tinh tri gia trong nuoc & ngoai nuoc
        cot = Excel.WorksheetFunction.Match(.Cells(15, 7), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
         If .Range("J" & i) = "Vi" & ChrW(7879) & "t Nam" Then ' có xuat xu
             .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia có xuat xu
             .Range("H" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia có xuat xu
         Else: .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia không xuat xu
         .Range("I" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia không xuat xu
         End If
           
    Next

lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
' gán két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    'lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).Row
    For k = 16 To lastRow
        For Each r In ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2)
            If r = .Cells(k, 17) Then
                 result1 = result1 & ";" & r.Offset(0, -22) ' lay stk dua vào 1 o excel
                .Range("K" & k) = Right(result1, Len(result1) - 1) ' bo dau cham phay o dau di
                 result2 = "'" & result2 & " " & r.Offset(0, -21) ' lay ngay tk dua vào 1 o excel, dau "'" dung sua loi ngay thang
                .Range("T" & k) = Right(result2, Len(result2) - 1) ' bo dau cham + phay o dau di
                '.Range("L" & k).NumberFormat = "mm/dd/yyyy" ' dinh dang ngay thang nam
                 result3 = result3 & ";" & r.Offset(0, -19) ' lay dong hang tk dua vào 1 o excel
                .Range("O" & k) = Right(result3, Len(result3) - 1) ' bo dau cham phai o dau di
                If .Range("S" & k) = "" Then
                     result4 = result4 & ";" & r.Offset(0, -9) ' lay so CO  dua vào 1 o excel
                    .Range("M" & k) = Right(result4, Len(result4) - 1) & "; Ty gia " & .Cells(k, 18).Value ' bo dau cham phai o dau di
                     result5 = "'" & result5 & " " & r.Offset(0, -8) ' lay ngay CO  dua vào 1 o excel, dau "'" dung sua loi ngay thang
                    .Range("U" & k) = Right(result5, Len(result5) - 1) ' bo dau cham phay o dau di
                Else: .Range("N" & k) = ""
                End If
            End If
         Next
         
         'remove khoang trang o dau
          findStartNumL = Application.WorksheetFunction.Find(" ", .Range("T" & k))
         .Range("L" & k) = Application.WorksheetFunction.Replace(.Range("T" & k), findStartNumL, 1, "") 'remove khoang trang o dau
         
         'remove khoang trang o dau
         If .Range("U" & k) <> "" Then
            findStartNumN = Application.WorksheetFunction.Find(" ", .Range("U" & k))
            .Range("N" & k) = Application.WorksheetFunction.Replace(.Range("U" & k), findStartNumN, 1, "") 'remove khoang trang o dau
         End If
 
         If Left(.Range("N" & k), 1) = ";" Then
            .Range("N" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
          If Left(.Range("M" & k), 1) = ";" Then
            .Range("M" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
         
' tra két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    Next
     .Range("T16:U" & lastRow) = "" ' xoa cot phu di
     .Range("Q16:Q" & lastRow) = "" ' xoa cot phu di
 
' an hàng rong  khong chua du lieu
    For i = 16 To 1585
        If .Range("A" & i) = "" Then
            Worksheets("CTH").Rows(i).Hidden = True
        End If
    Next
 ' an cot du thua di
        .Range("O1:Y1").EntireColumn.Hidden = True
    
' tinh toan gia tri footer
    .Range("H1588") = Application.WorksheetFunction.Sum(.Range("H16:H1585")) ' tong trong nuoc
    .Range("I1588") = Application.WorksheetFunction.Sum(.Range("I16:I1585")) ' tong nuoc ngoai
    ' tong II chi phi nhan cong truc tiep
        .Range("I1590") = .Range("P1590") * .Range("K10") 'luong thuong
        .Range("I1591") = .Range("P1591") * .Range("K10") ' phuc loi y te
        .Range("I1593") = .Range("I1590") + .Range("I1591")
    ' tong III chi phi phan bo truc tiep
        .Range("I1595") = .Range("P1595") * .Range("K10") 'thue nhà xuong
        .Range("I1596") = .Range("P1596") * .Range("K10") 'khau hao
        .Range("I1597") = .Range("P1597") * .Range("K10") 'khau hao
        .Range("I1599") = .Range("I1595") + .Range("I1596") + .Range("I1597")
        .Range("I1604") = .Range("K11") ' tong VIII giá FOB
        .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
        .Range("I1602") = .Range("I1604") - .Range("I1603") ' tong VI gia xuat xuong
        .Range("I1600") = .Range("H1588") + .Range("I1588") + .Range("I1593") + .Range("I1599") ' tong IV chi phi xuat xuong
        .Range("I1601") = .Range("I1602") - .Range("I1600") ' tong VI gia xuat xuong
        
      ' Tinh LVC
         .Range("J1606") = Round(.Range("I1604"), 2) & "   - " ' 'Gia FOB
         .Range("J1609") = Round(.Range("I1604"), 2) 'Gia FOB
         .Range("C1586") = Round(Application.WorksheetFunction.SumIf(.Range("J16:J1585"), _
         "Vi" & ChrW(7879) & "t Nam", .Range("H16:H1585")), 2)
         'tim gia nl ko có xx chrwgo tieng viet co dau,Ctr + G mo cua so immediate => gơ tieng viet vao o selection
          .Range("K1606") = .Range("I1588") + .Range("H1588") - .Range("C1586")
          .Range("C1587") = .Range("K1606")
          .Range("M1607") = Round((.Range("J1609") - .Range("K1606")) / .Range("J1609") * 100, 2) & " %" ' tinh LVC
         
'copy LVC tu wb goc sang wb moi khoi tao

        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            ' copy paste value
            Range("A1:AA1623").Copy
            Range("A1:AA1623").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = .Range("Q10") ' dat ten sheet vua moi past
            
            
                ' tao file PDF ****
            With ActiveSheet.PageSetup
                ' Can trang gi?ng Print Preview
                .Orientation = xlLandscape ' ho?c xlLandscape tùy b?n
                .PaperSize = xlPaperA4
                .FitToPagesWide = 1
                .FitToPagesTall = 1
                ' L? chu?n (có th? tùy ch?nh)
                .TopMargin = Application.InchesToPoints(0.1)
                .BottomMargin = Application.InchesToPoints(0.1)
                .LeftMargin = Application.InchesToPoints(0.1)
                .RightMargin = Application.InchesToPoints(0.1)
            End With
            ' ? L?nh xu?t PDF gi?ng h?t Print Preview
                 ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, _
                IgnorePrintAreas:=False, _
                fileName:=xPath & "\" & ActiveSheet.Name
            
    
             ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh ' tao sheet moi tren wb moi
    
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A17:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
       
    Next ' ****** cot moc vong lap de xuat file excel

        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel

lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub


Sub index_MatchCTSH3()
Dim lookupRange, vlookupRange, lookupRangeXK1, lookupRangeXK2, r As Range 'tao bien r chay
Dim i, j, k, l, stt, hang, cot, lastRow, lastRow2, lastRow3, lastRow4, lastRow5 As Long
Dim result1, result2, result3, result4, result5 As String
Dim findStartNumL, findStartNumN As Integer
With ThisWorkbook.Sheets("CTSH")
lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("DM").Cells(.Rows.Count, "F").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:Q" & lastRow2)


'cài dat thoi han su dung
Dim hanchot As Date
    hanchot = DateSerial(2025, 12, 31)
        If Now() > hanchot Then
            MsgBox "Qua han su dung " & CStr(hanchot)
            ThisWorkbook.Close SaveChanges:=False
        End If

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel


'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path

    sFileName = "CTSH" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        

' dien du lieu header
lastRow5 = .Cells(.Rows.Count, "W").End(xlUp).row
lastRow4 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "U").End(xlUp).row
Set lookupRangeXK1 = ThisWorkbook.Sheets("XK").Range("B11:BB" & lastRow4)
Set lookupRangeXK2 = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow4)
        .Range("P6") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 10, 0) ' ty gia
        .Range("O8") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 17, 0) ' incoterm
        .Range("P10") = Application.WorksheetFunction.SumIf(ThisWorkbook.Sheets("XK").Range("B11:B" & lastRow4), _
        .Range("Q9"), ThisWorkbook.Sheets("XK").Range("AE11:AE" & lastRow4))  ' tong tri gia
        .Range("L10") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 11, 0) ' USD/VND
        .Range("L11") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 11, 0) ' USD/VND
    For l = 16 To lastRow5 ' ****** cot moc vong lap de xuat file excel
    ThisWorkbook.Sheets("CTSH").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & l) ' mă SP vao ô P7
        .Range("K7") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 7, 0) ' ten sp
        .Range("K8") = Left(Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 6, 0), 6) ' HS code sp
        .Range("P8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 9, 0) ' don gia
        .Range("L9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 12, 0) ' dvt
        .Range("K9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("P9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("K10") = .Range("P8") * .Range("P9") ' tri gia exw
        .Range("Q10") = .Range("V" & l) ' dat ten file
        .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB


' tim so luong dong ma dinh muc sp
    Set vlookupRange = ThisWorkbook.Sheets("DM").Range("B7:I" & lastRow3)
    .Range("P5") = Application.WorksheetFunction.CountIf(ThisWorkbook.Sheets("DM") _
    .Range("A7:A" & lastRow3), .Range("P7")) ' t́m sl dm
    .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
   
    
'chay vong lap dien gia tri
 lastRow = .Cells(.Rows.Count, "T").End(xlUp).row
    stt = 0
     For i = 16 To lastRow
         stt = stt + 1
        .Range("A" & i) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
        .Range("E" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 8, 0) ' lay dinh muc
        .Range("P" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 5, 0) ' lây mă nvl
        .Range("F" & i) = .Range("E" & i) * .Range("P9") ' tinh sl
        .Range("Q" & i) = .Range("Q9") & .Range("P" & i) ' tao cot phu
     Next
        
    For i = 16 To lastRow
    hang = Excel.WorksheetFunction.Match(.Cells(i, 17), ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2), 0)
       For j = 2 To 4
            cot = Excel.WorksheetFunction.Match(.Cells(15, j), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, j) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' dung ham index& match de lay data
       Next
            .Range("C" & i) = Left(.Range("C" & i), 6) ' lay 6 kư tu là hs code
            ' lay xuat xu
            cot = Excel.WorksheetFunction.Match(.Cells(15, 10), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 10) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            ' lay ty gia
            cot = Excel.WorksheetFunction.Match(.Cells(15, 18), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 18) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
             ' lay loai hinh
            cot = Excel.WorksheetFunction.Match(.Cells(15, 19), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 19) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            
        ' tinh tri gia trong nuoc & ngoai nuoc
        cot = Excel.WorksheetFunction.Match(.Cells(15, 7), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
         If .Range("J" & i) = "Vi" & ChrW(7879) & "t Nam" Then ' có xuat xu
             .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia có xuat xu
             .Range("H" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia có xuat xu
         Else: .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia không xuat xu
         .Range("I" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia không xuat xu
         End If
           
    Next

lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
' gán két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    'lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).Row
    For k = 16 To lastRow
        For Each r In ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2)
            If r = .Cells(k, 17) Then
                 result1 = result1 & ";" & r.Offset(0, -22) ' lay stk dua vào 1 o excel
                .Range("K" & k) = Right(result1, Len(result1) - 1) ' bo dau cham phay o dau di
                 result2 = "'" & result2 & " " & r.Offset(0, -21) ' lay ngay tk dua vào 1 o excel, dau "'" dung sua loi ngay thang
                .Range("T" & k) = Right(result2, Len(result2) - 1) ' bo dau cham + phay o dau di
                '.Range("L" & k).NumberFormat = "mm/dd/yyyy" ' dinh dang ngay thang nam
                 result3 = result3 & ";" & r.Offset(0, -19) ' lay dong hang tk dua vào 1 o excel
                .Range("O" & k) = Right(result3, Len(result3) - 1) ' bo dau cham phai o dau di
                If .Range("S" & k) = "" Then
                     result4 = result4 & ";" & r.Offset(0, -9) ' lay so CO  dua vào 1 o excel
                    .Range("M" & k) = Right(result4, Len(result4) - 1) & "; Ty gia " & .Cells(k, 18).Value ' bo dau cham phai o dau di
                     result5 = "'" & result5 & " " & r.Offset(0, -8) ' lay ngay CO  dua vào 1 o excel, dau "'" dung sua loi ngay thang
                    .Range("U" & k) = Right(result5, Len(result5) - 1) ' bo dau cham phay o dau di
                Else: .Range("N" & k) = ""
                End If
            End If
         Next
         
         'remove khoang trang o dau
          findStartNumL = Application.WorksheetFunction.Find(" ", .Range("T" & k))
         .Range("L" & k) = Application.WorksheetFunction.Replace(.Range("T" & k), findStartNumL, 1, "") 'remove khoang trang o dau
         
         'remove khoang trang o dau
         If .Range("U" & k) <> "" Then
            findStartNumN = Application.WorksheetFunction.Find(" ", .Range("U" & k))
            .Range("N" & k) = Application.WorksheetFunction.Replace(.Range("U" & k), findStartNumN, 1, "") 'remove khoang trang o dau
         End If
 
         If Left(.Range("N" & k), 1) = ";" Then
            .Range("N" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
          If Left(.Range("M" & k), 1) = ";" Then
            .Range("M" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
         
' tra két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    Next
     .Range("T16:U" & lastRow) = "" ' xoa cot phu di
     .Range("Q16:Q" & lastRow) = "" ' xoa cot phu di
 
' an hàng rong  khong chua du lieu
    For i = 16 To 1585
        If .Range("A" & i) = "" Then
            Worksheets("CTSH").Rows(i).Hidden = True
        End If
    Next
 ' an cot du thua di
        .Range("O1:Y1").EntireColumn.Hidden = True
    
' tinh toan gia tri footer
    .Range("H1588") = Application.WorksheetFunction.Sum(.Range("H16:H1585")) ' tong trong nuoc
    .Range("I1588") = Application.WorksheetFunction.Sum(.Range("I16:I1585")) ' tong nuoc ngoai
    ' tong II chi phi nhan cong truc tiep
        .Range("I1590") = .Range("P1590") * .Range("K10") 'luong thuong
        .Range("I1591") = .Range("P1591") * .Range("K10") ' phuc loi y te
        .Range("I1593") = .Range("I1590") + .Range("I1591")
    ' tong III chi phi phan bo truc tiep
        .Range("I1595") = .Range("P1595") * .Range("K10") 'thue nhà xuong
        .Range("I1596") = .Range("P1596") * .Range("K10") 'khau hao
        .Range("I1597") = .Range("P1597") * .Range("K10") 'khau hao
        .Range("I1599") = .Range("I1595") + .Range("I1596") + .Range("I1597")
        .Range("I1604") = .Range("K11") ' tong VIII giá FOB
        .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
        .Range("I1602") = .Range("I1604") - .Range("I1603") ' tong VI gia xuat xuong
        .Range("I1600") = .Range("H1588") + .Range("I1588") + .Range("I1593") + .Range("I1599") ' tong IV chi phi xuat xuong
        .Range("I1601") = .Range("I1602") - .Range("I1600") ' tong VI gia xuat xuong
        
      ' Tinh LVC
         .Range("J1606") = Round(.Range("I1604"), 2) & "   - " ' 'Gia FOB
         .Range("J1609") = Round(.Range("I1604"), 2) 'Gia FOB
         .Range("C1586") = Round(Application.WorksheetFunction.SumIf(.Range("J16:J1585"), _
         "Vi" & ChrW(7879) & "t Nam", .Range("H16:H1585")), 2)
         'tim gia nl ko có xx chrwgo tieng viet co dau,Ctr + G mo cua so immediate => gơ tieng viet vao o selection
          .Range("K1606") = .Range("I1588") + .Range("H1588") - .Range("C1586")
          .Range("C1587") = .Range("K1606")
          .Range("M1607") = Round((.Range("J1609") - .Range("K1606")) / .Range("J1609") * 100, 2) & " %" ' tinh LVC
         
'copy LVC tu wb goc sang wb moi khoi tao

        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            ' copy paste value
            Range("A1:AA1623").Copy
            Range("A1:AA1623").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = .Range("Q10") ' dat ten sheet vua moi past
            
            
                ' tao file PDF ****
            With ActiveSheet.PageSetup
                ' Can trang gi?ng Print Preview
                .Orientation = xlLandscape ' ho?c xlLandscape tùy b?n
                .PaperSize = xlPaperA4
                .FitToPagesWide = 1
                .FitToPagesTall = 1
                ' L? chu?n (có th? tùy ch?nh)
                .TopMargin = Application.InchesToPoints(0.1)
                .BottomMargin = Application.InchesToPoints(0.1)
                .LeftMargin = Application.InchesToPoints(0.1)
                .RightMargin = Application.InchesToPoints(0.1)
            End With
            ' ? L?nh xu?t PDF gi?ng h?t Print Preview
                 ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, _
                IgnorePrintAreas:=False, _
                fileName:=xPath & "\" & ActiveSheet.Name
            
    
             ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh ' tao sheet moi tren wb moi
    
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A17:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
       
    Next ' ****** cot moc vong lap de xuat file excel

        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel

lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub

Sub index_MatchWOIII3()
Dim lookupRange, vlookupRange, lookupRangeXK1, lookupRangeXK2, r As Range 'tao bien r chay
Dim i, j, k, l, stt, hang, cot, lastRow, lastRow2, lastRow3, lastRow4, lastRow5 As Long
Dim result1, result2, result3, result4, result5 As String
Dim findStartNumL, findStartNumN As Integer
With ThisWorkbook.Sheets("WOIII")
lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("DM").Cells(.Rows.Count, "F").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:Q" & lastRow2)


'cài dat thoi han su dung
Dim hanchot As Date
    hanchot = DateSerial(2025, 5, 31)
        If Now() > hanchot Then
            MsgBox "Qua han su dung " & CStr(hanchot)
            ThisWorkbook.Close SaveChanges:=False
        End If

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel


'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path

    sFileName = "WOIII" ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb
        

' dien du lieu header
lastRow5 = .Cells(.Rows.Count, "W").End(xlUp).row
lastRow4 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "U").End(xlUp).row
Set lookupRangeXK1 = ThisWorkbook.Sheets("XK").Range("B11:BB" & lastRow4)
Set lookupRangeXK2 = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow4)
        .Range("P6") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 10, 0) ' ty gia
        .Range("O8") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 17, 0) ' incoterm
        .Range("P10") = Application.WorksheetFunction.SumIf(ThisWorkbook.Sheets("XK").Range("B11:B" & lastRow4), _
        .Range("Q9"), ThisWorkbook.Sheets("XK").Range("AE11:AE" & lastRow4))  ' tong tri gia
    For l = 16 To lastRow5 ' ****** cot moc vong lap de xuat file excel
    ThisWorkbook.Sheets("WOIII").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & l) ' mă SP vao ô P7
        .Range("J7") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 7, 0) ' ten sp
        .Range("J8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 6, 0) ' HS code sp
        .Range("P8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 9, 0) ' don gia
        .Range("K9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 12, 0) ' dvt
        .Range("J9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("P9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("J10") = .Range("P8") * .Range("P9") ' tri gia exw
        .Range("Q10") = .Range("V" & l) ' dat ten file
        .Range("J11") = .Range("J10") + (.Range("J10") / .Range("P10")) * Range("P103") ' tri gia FOB


' tim so luong dong ma dinh muc sp
    Set vlookupRange = ThisWorkbook.Sheets("DM").Range("B7:I" & lastRow3)
    .Range("P5") = Application.WorksheetFunction.CountIf(ThisWorkbook.Sheets("DM") _
    .Range("A7:A" & lastRow3), .Range("P7")) ' t́m sl dm
    .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
   
    
'chay vong lap dien gia tri
 lastRow = .Cells(.Rows.Count, "T").End(xlUp).row
    stt = 0
     For i = 16 To lastRow
         stt = stt + 1
        .Range("A" & i) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
        .Range("E" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 8, 0) ' lay dinh muc
        .Range("P" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 5, 0) ' lây mă nvl
        .Range("F" & i) = .Range("E" & i) * .Range("P9") ' tinh sl
        .Range("Q" & i) = .Range("Q9") & .Range("P" & i) ' tao cot phu
     Next
        
    For i = 16 To lastRow
    hang = Excel.WorksheetFunction.Match(.Cells(i, 17), ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2), 0)
       For j = 2 To 3
            cot = Excel.WorksheetFunction.Match(.Cells(15, j), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, j) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' dung ham index& match de lay data
       Next
            .Range("C" & i) = Left(.Range("C" & i), 6) ' là hs code
            ' lay xuat xu
            cot = Excel.WorksheetFunction.Match(.Cells(15, 10), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 10) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            ' lay ty gia
            cot = Excel.WorksheetFunction.Match(.Cells(15, 18), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 18) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
             ' lay loai hinh
            cot = Excel.WorksheetFunction.Match(.Cells(15, 19), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 19) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            
        ' tinh tri gia trong nuoc & ngoai nuoc
        cot = Excel.WorksheetFunction.Match(.Cells(15, 7), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
        If .Range("S" & i) = "" Then ' ma lh de trong => mua trong nuoc
            .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia trong nuoc
            .Range("H" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia trong nuoc
        Else: .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia ngoai nuoc
        .Range("I" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia ngoai nuoc
        End If
           
    Next

lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
' gán két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    'lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).Row
    For k = 16 To lastRow
        For Each r In ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2)
            If r = .Cells(k, 17) Then
                 result1 = result1 & ";" & r.Offset(0, -22) ' lay stk dua vào 1 o excel
                .Range("K" & k) = Right(result1, Len(result1) - 1) ' bo dau cham phay o dau di
                 result2 = "'" & result2 & " " & r.Offset(0, -21) ' lay ngay tk dua vào 1 o excel, dau "'" dung sua loi ngay thang
                .Range("T" & k) = Right(result2, Len(result2) - 1) ' bo dau cham + phay o dau di
                '.Range("L" & k).NumberFormat = "mm/dd/yyyy" ' dinh dang ngay thang nam
                 result3 = result3 & ";" & r.Offset(0, -19) ' lay dong hang tk dua vào 1 o excel
                .Range("O" & k) = Right(result3, Len(result3) - 1) ' bo dau cham phai o dau di
                If .Range("S" & k) = "" Then
                     result4 = result4 & ";" & r.Offset(0, -9) ' lay so CO  dua vào 1 o excel
                    .Range("M" & k) = Right(result4, Len(result4) - 1) & "; Ty gia " & .Cells(k, 18).Value ' bo dau cham phai o dau di
                     result5 = "'" & result5 & " " & r.Offset(0, -8) ' lay ngay CO  dua vào 1 o excel, dau "'" dung sua loi ngay thang
                    .Range("U" & k) = Right(result5, Len(result5) - 1) ' bo dau cham phay o dau di
                Else: .Range("N" & k) = "Linh kien"
                End If
            End If
         Next
         
         'remove khoang trang o dau
          findStartNumL = Application.WorksheetFunction.Find(" ", .Range("T" & k))
         .Range("L" & k) = Application.WorksheetFunction.Replace(.Range("T" & k), findStartNumL, 1, "") 'remove khoang trang o dau
         
         'remove khoang trang o dau
         If .Range("U" & k) <> "" Then
            findStartNumN = Application.WorksheetFunction.Find(" ", .Range("U" & k))
            .Range("N" & k) = Application.WorksheetFunction.Replace(.Range("U" & k), findStartNumN, 1, "") 'remove khoang trang o dau
         End If
 
         If Left(.Range("N" & k), 1) = ";" Then
            .Range("N" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
          If Left(.Range("M" & k), 1) = ";" Then
            .Range("M" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
         
' tra két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    Next
     .Range("T16:U" & lastRow) = "" ' xoa cot phu di
     .Range("Q16:Q" & lastRow) = "" ' xoa cot phu di
 
' an hàng rong  khong chua du lieu
    For i = 16 To 85
        If .Range("A" & i) = "" Then
            Worksheets("WOIII").Rows(i).Hidden = True
        End If
    Next
 ' an cot du thua di
        .Range("O1:Y1").EntireColumn.Hidden = True
    
' tinh toan gia tri footer
    .Range("H88") = Application.WorksheetFunction.Sum(.Range("H16:H85")) ' tong trong nuoc
    .Range("I88") = Application.WorksheetFunction.Sum(.Range("I16:I85")) ' tong nuoc ngoai
    ' tong II chi phi nhan cong truc tiep
        .Range("I90") = .Range("P90") * .Range("K10") 'luong thuong
        .Range("I91") = .Range("P91") * .Range("K10") ' phuc loi y te
        .Range("I93") = .Range("I90") + .Range("I91")
    ' tong III chi phi phan bo truc tiep
        .Range("I95") = .Range("P95") * .Range("K10") 'thue nhà xuong
        .Range("I96") = .Range("P96") * .Range("K10") 'khau hao
        .Range("I97") = .Range("P97") * .Range("K10") 'khau hao
        .Range("I99") = .Range("I95") + .Range("I96") + .Range("I97")
        .Range("I104") = .Range("K11") ' tong VIII giá FOB
        .Range("I103") = (.Range("K10") / .Range("P10")) * .Range("P103") ' tong VII phi van chuyen
        .Range("I102") = .Range("I104") - .Range("I103") ' tong VI gia xuat xuong
        .Range("I100") = .Range("H88") + .Range("I88") + .Range("I93") + .Range("I99") ' tong IV chi phi xuat xuong
        .Range("I101") = .Range("I102") - .Range("I100") ' tong VI gia xuat xuong
        
      ' Tinh LVC
         .Range("J106") = Round(.Range("I104"), 2) & "   - " ' 'Gia FOB
         .Range("J109") = Round(.Range("I104"), 2) 'Gia FOB
         .Range("C86") = Round(Application.WorksheetFunction.SumIf(.Range("J16:J85"), _
         "Vi" & ChrW(7879) & "t Nam", .Range("H16:H85")), 2)
         'tim gia nl ko có xx chrwgo tieng viet co dau,Ctr + G mo cua so immediate => gơ tieng viet vao o selection
          .Range("K106") = .Range("I88") + .Range("H88") - .Range("C86")
          .Range("C87") = .Range("K106")
          .Range("M107") = Round((.Range("J109") - .Range("K106")) / .Range("J109") * 100, 2) & " %" ' tinh LVC
         
'copy LVC tu wb goc sang wb moi khoi tao

        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            ' copy paste value
            Range("A1:AA500").Copy
            Range("A1:AA500").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = .Range("Q10") ' dat ten sheet vua moi past
             ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh ' tao sheet moi tren wb moi
    
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U85") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A17:A85").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
       
    Next ' ****** cot moc vong lap de xuat file excel

        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel

lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub



Sub index_MatchRVC3()
Dim lookupRange, vlookupRange, lookupRangeXK1, lookupRangeXK2, r As Range 'tao bien r chay
Dim i, j, k, l, stt, hang, cot, lastRow, lastRow2, lastRow3, lastRow4, lastRow5 As Long
Dim result1, result2, result3, result4, result5 As String
Dim findStartNumL, findStartNumN As Integer
With ThisWorkbook.Sheets("RVC")
lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "E").End(xlUp).row
lastRow3 = ThisWorkbook.Sheets("DM").Cells(.Rows.Count, "F").End(xlUp).row
Set lookupRange = ThisWorkbook.Sheets("Save").Range("A2:Q" & lastRow2)


'cài dat thoi han su dung
Dim hanchot As Date
    hanchot = DateSerial(2025, 12, 31)
        If Now() > hanchot Then
            MsgBox "Qua han su dung " & CStr(hanchot)
            ThisWorkbook.Close SaveChanges:=False
        End If
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

'dat bien tao wb moi
Dim wb, newWb As Workbook
Dim Sh As Worksheet
Dim sFileName As String ' dua con tro vao file name trong o J8
Dim xPath As String ' tao duong dan
xPath = Application.ActiveWorkbook.Path

    sFileName = "RVC" & .Range("Q9") ' dat ten file cho wb
    Set wb = CreateNewWb(sFileName) 'goi ham tao workbook,
    Set newWb = wb ' dat bien newWb de quay ve select newwb

' dien du lieu header
lastRow5 = .Cells(.Rows.Count, "W").End(xlUp).row
lastRow4 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "U").End(xlUp).row
Set lookupRangeXK1 = ThisWorkbook.Sheets("XK").Range("B11:BB" & lastRow4)
Set lookupRangeXK2 = ThisWorkbook.Sheets("XK").Range("Q11:BB" & lastRow4)
        .Range("P6") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 10, 0) ' ty gia
        .Range("O8") = Application.WorksheetFunction.VLookup(.Range("Q9"), lookupRangeXK1, 17, 0) ' incoterm
        .Range("P10") = Application.WorksheetFunction.SumIf(ThisWorkbook.Sheets("XK").Range("B11:B" & lastRow4), _
        .Range("Q9"), ThisWorkbook.Sheets("XK").Range("AE11:AE" & lastRow4))  ' tong tri gia
    For l = 16 To lastRow5 ' ****** cot moc vong lap de xuat file excel
    ThisWorkbook.Sheets("RVC").Activate ' chuyen select sang wb goc de khac phuc loi
        .Range("P7") = .Range("W" & l) ' mă SP vao ô P7
        .Range("K7") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 7, 0) ' ten sp
        .Range("K8") = Left(Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 6, 0), 6) ' HS code sp
        .Range("P8") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 9, 0) ' don gia
        .Range("L9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 12, 0) ' dvt
        .Range("K9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("P9") = Application.WorksheetFunction.VLookup(.Range("V" & l), lookupRangeXK2, 11, 0) ' so luong
        .Range("K10") = .Range("P8") * .Range("P9") ' tri gia exw
        .Range("I10") = "Tri giá " & .Range("O8") '  incoterm
        .Range("L10") = "USD"
        .Range("L11") = "USD"
        .Range("Q10") = .Range("V" & l) ' dat ten file
        .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB


' tim so luong dong ma dinh muc sp
    Set vlookupRange = ThisWorkbook.Sheets("DM").Range("B7:I" & lastRow3)
    .Range("P5") = Application.WorksheetFunction.CountIf(ThisWorkbook.Sheets("DM") _
    .Range("A7:A" & lastRow3), .Range("P7")) ' t́m sl dm
    .Cells(.Range("P5") + 15, 20) = .Range("P5") ' gán sl vào dong cuoi o cot T
   
    
'chay vong lap dien gia tri
 lastRow = .Cells(.Rows.Count, "T").End(xlUp).row
    stt = 0
     For i = 16 To lastRow
         stt = stt + 1
        .Range("A" & i) = stt ' dien stt, dùng de lien ket ma nvl cho vlookup
        .Range("E" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 8, 0) ' lay dinh muc
        .Range("P" & i) = Application.WorksheetFunction.VLookup(.Range("A" & i) & .Range("P7"), vlookupRange, 5, 0) ' lây mă nvl
        .Range("F" & i) = .Range("E" & i) * .Range("P9") ' tinh sl
        .Range("Q" & i) = .Range("Q9") & .Range("P" & i) ' tao cot phu
     Next
        
    For i = 16 To lastRow
    hang = Excel.WorksheetFunction.Match(.Cells(i, 17), ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2), 0)
       For j = 2 To 4
            cot = Excel.WorksheetFunction.Match(.Cells(15, j), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, j) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' dung ham index& match de lay data
       Next
            .Range("C" & i) = Left(.Range("C" & i), 6) ' lay 6 kư tu là hs code
            ' lay xuat xu
            cot = Excel.WorksheetFunction.Match(.Cells(15, 10), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 10) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            ' lay ty gia
            cot = Excel.WorksheetFunction.Match(.Cells(15, 18), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 18) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
             ' lay loai hinh
            cot = Excel.WorksheetFunction.Match(.Cells(15, 19), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
            .Cells(i, 19) = Excel.WorksheetFunction.Index(lookupRange, hang, cot)
            
        ' tinh tri gia trong nuoc & ngoai nuoc
        cot = Excel.WorksheetFunction.Match(.Cells(15, 7), ThisWorkbook.Sheets("Save").Range("A1:W1"), 0)
        If .Range("S" & i) = "" Or .Range("S" & i) = "E15" Then ' ma lh de trong => mua trong nuoc
            .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia trong nuoc
            .Range("H" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia trong nuoc
        Else: .Range("G" & i) = Excel.WorksheetFunction.Index(lookupRange, hang, cot) ' tinh don gia ngoai nuoc
        .Range("I" & i) = .Range("F" & i) * .Range("G" & i) 'tinh tri gia ngoai nuoc
        End If
           
    Next

lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "W").End(xlUp).row
' gán két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    'lastRow2 = ThisWorkbook.Sheets("Save").Cells(.Rows.Count, "A").End(xlUp).Row
    For k = 16 To lastRow
        For Each r In ThisWorkbook.Sheets("Save").Range("W2:W" & lastRow2)
            If r = .Cells(k, 17) Then
                 result1 = result1 & ";" & r.Offset(0, -22) ' lay stk dua vào 1 o excel
                .Range("K" & k) = Right(result1, Len(result1) - 1) ' bo dau cham phay o dau di
                 result2 = "'" & result2 & " " & r.Offset(0, -21) ' lay ngay tk dua vào 1 o excel, dau "'" dung sua loi ngay thang
                .Range("T" & k) = Right(result2, Len(result2) - 1) ' bo dau cham + phay o dau di
                '.Range("L" & k).NumberFormat = "mm/dd/yyyy" ' dinh dang ngay thang nam
                 result3 = result3 & ";" & r.Offset(0, -19) ' lay dong hang tk dua vào 1 o excel
                .Range("O" & k) = Right(result3, Len(result3) - 1) ' bo dau cham phai o dau di
                If .Range("S" & k) = "" Then
                     result4 = result4 & ";" & r.Offset(0, -9) ' lay so CO  dua vào 1 o excel
                    .Range("M" & k) = Right(result4, Len(result4) - 1) & "; Ty gia " & .Cells(k, 18).Value ' bo dau cham phai o dau di
                     result5 = "'" & result5 & " " & r.Offset(0, -8) ' lay ngay CO  dua vào 1 o excel, dau "'" dung sua loi ngay thang
                    .Range("U" & k) = Right(result5, Len(result5) - 1) ' bo dau cham phay o dau di
                Else: .Range("N" & k) = ""
                End If
            End If
         Next
         
         'remove khoang trang o dau
          findStartNumL = Application.WorksheetFunction.Find(" ", .Range("T" & k))
         .Range("L" & k) = Application.WorksheetFunction.Replace(.Range("T" & k), findStartNumL, 1, "") 'remove khoang trang o dau
         
         'remove khoang trang o dau
         If .Range("U" & k) <> "" Then
            findStartNumN = Application.WorksheetFunction.Find(" ", .Range("U" & k))
            .Range("N" & k) = Application.WorksheetFunction.Replace(.Range("U" & k), findStartNumN, 1, "") 'remove khoang trang o dau
         End If
 
         If Left(.Range("N" & k), 1) = ";" Then
            .Range("N" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
          If Left(.Range("M" & k), 1) = ";" Then
            .Range("M" & k).Characters(1, 1).Font.Color = vbWhite ' to mau ky tu "'" dau
         End If
         
' tra két qua ban dau bang rong
    result1 = ""
    result2 = ""
    result3 = ""
    result4 = ""
    result5 = ""
    Next
     .Range("T16:U" & lastRow) = "" ' xoa cot phu di
     .Range("Q16:Q" & lastRow) = "" ' xoa cot phu di
 
' an hàng rong  khong chua du lieu
    For i = 16 To 1585
        If .Range("A" & i) = "" Then
            Worksheets("RVC").Rows(i).Hidden = True
        End If
    Next
 ' an cot du thua di
        .Range("O1:Y1").EntireColumn.Hidden = True
    
' tinh toan gia tri footer
    .Range("H1588") = Application.WorksheetFunction.Sum(.Range("H16:H1585")) ' tong trong nuoc
    .Range("I1588") = Application.WorksheetFunction.Sum(.Range("I16:I1585")) ' tong nuoc ngoai
    ' tong II chi phi nhan cong truc tiep
        .Range("I1590") = .Range("P1590") * .Range("K10") 'luong thuong
        .Range("I1591") = .Range("P1591") * .Range("K10") ' phuc loi y te
        .Range("I1593") = .Range("I1590") + .Range("I1591")
    ' tong III chi phi phan bo truc tiep
        .Range("I1595") = .Range("P1595") * .Range("K10") 'thue nhà xuong
        .Range("I1596") = .Range("P1596") * .Range("K10") 'khau hao
        .Range("I1597") = .Range("P1597") * .Range("K10") 'khau hao
        .Range("I1599") = .Range("I1595") + .Range("I1596") + .Range("I1597")
    
    ' tong IV chi phi xuat xuong
         .Range("I1600") = .Range("H1588") + .Range("I1588") + .Range("I1593") + .Range("I1599")

        If .Range("O8") = "EXW" Or .Range("O8") = "FCR" Then ' neu tk khai giá EXW
            .Range("K11") = .Range("K10") + (.Range("K10") / .Range("P10")) * Range("P1603") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            .Range("I1602") = .Range("K10") ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1604") = .Range("K11") ' tong VIII giá FOB
            
        ElseIf .Range("O8") = "FOB" Then ' neu tk khai giá FOB
            .Range("K11") = .Range("K10") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            .Range("I1604") = .Range("K11") ' tong VIII giá FOB
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1602") = .Range("I1604") - .Range("I1603")  ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
                
        Else ' truong hop nhóm C & D nhu CFR,CIF,CPT,DAP,DDU,DDP
        Dim freight As Long
            freight = (.Range("K10") / .Range("P10")) * .Range("P1604") ' cuoc biên
            .Range("I1604") = .Range("K10") - freight ' tong VIII giá FOB
            .Range("I1603") = (.Range("K10") / .Range("P10")) * .Range("P1603") ' tong VII phi van chuyen
            .Range("I1602") = .Range("I1604") - .Range("I1603") ' tong VI gia xuat xuong
            .Range("I1601") = .Range("I1602") - .Range("I1600") ' Loi nhuan
            .Range("K11") = .Range("I1604") ' tri gia FOB
            '.Range("B11") = ChrW(272) & ChrW(417) & ChrW(110) & " giá FOB: " & .Range("K11") / .Range("K9") & " USD" ' don gia FOB
            
        End If
        
      ' Tinh LVC
         .Range("J1606") = Round(.Range("I1604"), 2) & "   - " ' 'Gia FOB
         .Range("J1609") = Round(.Range("I1604"), 2) 'Gia FOB
         .Range("C1586") = Round(Application.WorksheetFunction.SumIf(.Range("J16:J1585"), _
         "Vi" & ChrW(7879) & "t Nam", .Range("H16:H1585")), 2)
         'tim gia nl ko có xx chrwgo tieng viet co dau,Ctr + G mo cua so immediate => gơ tieng viet vao o selection
          .Range("K1606") = .Range("I1588") + .Range("H1588") - .Range("C1586")
          .Range("C1587") = .Range("K1606")
          .Range("M1607") = Round((.Range("J1609") - .Range("K1606")) / .Range("J1609") * 100, 2) & " %" ' tinh LVC
         
'copy LVC tu wb goc sang wb moi khoi tao

        For Each Sh In ActiveWindow.SelectedSheets ' bien sh chay tu cac sheet dang chon
            Sh.Copy wb.Sheets(1) ' copy sheet cu sang sheet moi
            ' copy paste value
            Range("A1:AA1623").Copy
            Range("A1:AA1623").PasteSpecial Paste:=xlPasteValues
            Application.CutCopyMode = False ' bo lua chon select di
            ActiveSheet.Name = .Range("Q10") ' dat ten sheet vua moi past
            
            ' tao file PDF ****
            With ActiveSheet.PageSetup
                ' Can trang gi?ng Print Preview
                .Orientation = xlLandscape ' ho?c xlLandscape tùy b?n
                .PaperSize = xlPaperA4
                .FitToPagesWide = 1
                .FitToPagesTall = 1
                ' L? chu?n (có th? tùy ch?nh)
                .TopMargin = Application.InchesToPoints(0.1)
                .BottomMargin = Application.InchesToPoints(0.1)
                .LeftMargin = Application.InchesToPoints(0.1)
                .RightMargin = Application.InchesToPoints(0.1)
            End With
            ' ? L?nh xu?t PDF gi?ng h?t Print Preview
                 ActiveSheet.ExportAsFixedFormat Type:=xlTypePDF, _
                IgnorePrintAreas:=False, _
                fileName:=xPath & "\" & ActiveSheet.Name
            
                
            
            ' di chuyen ve dau tien
            ActiveWindow.ScrollRow = 1
            ActiveWindow.ScrollColumn = 1
        Next Sh ' tao sheet moi tren wb moi
    
        ThisWorkbook.Activate ' chon wb cu
        .Range("A16:U1585") = "" 'xoa data bang lvc o wb cu di
   
        If Err <> 0 Then
            MsgBox Err.Description, vbCritical
        End If
        
        ' unhide dong hàng dan an truoc do
        .Range("A17:A1585").EntireRow.Hidden = False
        ' hien cot du thua
        .Range("O1:Y1").EntireColumn.Hidden = False
        
       
    Next ' ****** cot moc vong lap de xuat file excel

        newWb.Activate ' quay tro ve wb moi khoi tao
        Application.ActiveWorkbook.SaveAs fileName:=xPath & "\" & sFileName ' luu file vao duong dan hien tai cua file goc
        'wb.Close ' tat file excel

lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub



Function CreateNewWb(sWbName As String) As Workbook
 Dim oldWb As Workbook
 Set oldWb = ActiveWorkbook ' tra ve man hinh workbook cu
 Set CreateNewWb = Workbooks.Add ' tao moi workbook
 'CreateNewWb.SaveAs sWbName ' luu ten file theo filename
 oldWb.Activate
 End Function
 
 Function GetWb(sWbName As String, wb As Workbook) As Boolean ' kieu true or false
' neu GetWb = true thi WB tro vao workbook co ten o tham so sWbName
' neu GetWb = false thi chua co file co ten
    Dim i As Long ' kiem tra xem nhung wb dang open
    sWbName = UCase(sWbName)
        For i = 1 To Workbooks.Count
            If UCase(Workbooks(i).Name) = sWbName Then
                GetWb = True
                Set wb = Workbooks(i)
                Exit Function
            End If
         Next i
End Function
